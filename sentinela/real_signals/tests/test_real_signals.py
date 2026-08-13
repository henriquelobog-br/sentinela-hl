from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import zipfile

import httpx
import xarray as xr

from sentinela.persistence import ResearcherSignalStoreResult
from sentinela.core.models import EventStatus
from sentinela.real_signals.collectors import (
    CamsCollector, CmrCollector, CollectionResult, Merra2Collector,
)
from sentinela.real_signals.config import RealSignalSettings
from sentinela.real_signals.orchestrator import run_real_signals

NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


def settings(**changes):
    base = RealSignalSettings.from_env()
    return replace(base, **changes)


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://source.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failure", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return Response(next(self.payloads))

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return Response(next(self.payloads))


def cams_row(region="central_south_atlantic", value=0.4, valid_time="2026-08-04T12:00:00Z"):
    return {"region": region, "value": value, "unit": "1", "valid_time": valid_time, "analysis_time": "2026-08-04T00:00:00Z", "product": "cams-global"}


def cmr_row(
    granule="G123",
    updated="2026-08-04T11:00:00Z",
    time_start="2026-08-04T10:00:00Z",
    region=None,
):
    row = {"id": granule, "producer_granule_id": f"MOD04_L2.{granule}", "updated": updated, "time_start": time_start, "time_end": time_start}
    if region:
        row["region"] = region
    return row


def test_cams_valido_e_texto_factual():
    result = CamsCollector(settings(), records_loader=lambda now, regions: [cams_row()]).collect(NOW)
    assert result.received == 1
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "dust_transport_forecast"
    assert "0.4" in event.summary
    assert "chegada" not in event.summary.lower()


def test_cams_abaixo_do_threshold():
    result = CamsCollector(settings(cams_threshold=0.5), records_loader=lambda now, regions: [cams_row(value=0.4)]).collect(NOW)
    assert result.events == ()
    assert result.discarded == 1


def test_cams_regioes_progressao_e_costa():
    rows = [cams_row("east_south_atlantic"), cams_row("central_south_atlantic"), cams_row("brazil_coast")]
    result = CamsCollector(settings(), records_loader=lambda now, regions: rows).collect(NOW)
    categories = [event.category for event in result.events]
    assert "dust_corridor_progression" in categories
    assert "brazil_coast_approach" in categories


def test_cams_resposta_vazia():
    result = CamsCollector(
        settings(), records_loader=lambda now, regions: []
    ).collect(NOW)
    assert result.received == 0
    assert result.events == ()


def test_cams_erro_autenticacao_sanitizado():
    secret = "token-cams-nao-pode-vazar"

    def fail(now, regions):
        raise RuntimeError(secret)

    result = CamsCollector(settings(), records_loader=fail).collect(NOW)
    assert "autenticação" in result.error
    assert secret not in result.error


def test_cams_idempotencia_do_collector():
    collector = CamsCollector(
        settings(), records_loader=lambda now, regions: [cams_row()]
    )
    first = collector.collect(NOW)
    second = collector.collect(NOW)
    assert first.events[0].id == second.events[0].id


def test_cams_evidencia_normalizada():
    event = CamsCollector(
        settings(), records_loader=lambda now, regions: [cams_row()]
    ).collect(NOW).events[0]
    evidence = event.evidence[0]
    assert evidence["source"] == "CAMS"
    assert evidence["variable"] == settings().cams_variable
    assert evidence["region"] == "central_south_atlantic"
    assert evidence["value"] == 0.4
    assert evidence["threshold"] == settings().cams_threshold
    assert evidence["occurred_at"]
    assert evidence["retrieved_at"]


def test_cams_request_oficial_e_leitura_netcdf(tmp_path):
    class FakeCdsClient:
        def __init__(self):
            self.dataset = None
            self.request = None

        def retrieve(self, dataset, request, target):
            self.dataset = dataset
            self.request = request
            netcdf = Path(target).with_suffix(".nc")
            xr.Dataset(
                {
                    "dust_aerosol_optical_depth_550nm": (
                        ("valid_time", "latitude", "longitude"),
                        [[[0.4]]],
                        {"units": "1"},
                    )
                },
                coords={
                    "valid_time": [datetime(2026, 8, 4, 6)],
                    "latitude": [-20.0],
                    "longitude": [-15.0],
                },
            ).to_netcdf(netcdf, engine="scipy")
            with zipfile.ZipFile(target, "w") as archive:
                archive.write(netcdf, arcname="cams.nc")

    credentials = tmp_path / ".cdsapirc"
    credentials.write_text("configured", encoding="utf-8")
    client = FakeCdsClient()
    configured = settings(
        cams_region_ids=("central_south_atlantic",),
        cams_forecast_hours=(0,),
    )
    result = CamsCollector(
        configured,
        client=client,
        credentials_path=credentials,
    ).collect(NOW)
    assert client.dataset == "cams-global-atmospheric-composition-forecasts"
    assert client.request["variable"] == ["dust_aerosol_optical_depth_550nm"]
    assert client.request["data_format"] == "netcdf_zip"
    assert client.request["type"] == ["forecast"]
    assert client.request["area"] == [-10, -25, -35, -5]
    assert result.received == 1
    assert result.events[0].evidence[0]["value"] == 0.4


def test_cams_credencial_oficial_ausente(tmp_path):
    result = CamsCollector(
        settings(), credentials_path=tmp_path / "missing"
    ).collect(NOW)
    assert result.events == ()
    assert result.error == "credencial ADS ausente em ~/.cdsapirc"


def test_novo_granulo_cmr():
    client = Client([{"feed": {"entry": []}}, {"feed": {"entry": [cmr_row()]}}])
    result = CmrCollector(settings(), client).collect(NOW)
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "new_modis_aerosol_granule"
    assert "não confirma presença de poeira" in event.summary
    assert event.event_status is EventStatus.CATALOG_RECORD
    assert event.evidence[0]["granule_count"] == 1


def test_granulo_cmr_ja_processado():
    identity = "C1443533440-LAADS|G123|2026-08-04T11:00:00Z"
    client = Client([{"feed": {"entry": []}}, {"feed": {"entry": [cmr_row()]}}])
    result = CmrCollector(settings(), client, processed_ids=[identity]).collect(NOW)
    assert result.events == ()
    assert result.duplicates == 1


def test_cmr_idempotencia_entre_processos_independentes():
    first = CmrCollector(
        settings(),
        Client([{"feed": {"entry": []}}, {"feed": {"entry": [cmr_row()]}}]),
    ).collect(NOW)
    second = CmrCollector(
        settings(),
        Client([{"feed": {"entry": []}}, {"feed": {"entry": [cmr_row()]}}]),
    ).collect(NOW)

    first_run = run_real_signals(
        settings=settings(), sources=("cmr",), now=NOW,
        collectors={"cmr": FixedCollector(first)},
    )
    second_run = run_real_signals(
        settings=settings(), sources=("cmr",), now=NOW,
        collectors={"cmr": FixedCollector(second)},
    )

    assert first.events[0].id == second.events[0].id
    assert first.events[0].primary_claim_id == second.events[0].primary_claim_id
    assert first_run.signals[0].id == second_run.signals[0].id


def test_merra2_produto_indisponivel():
    result = Merra2Collector(settings(), Client([{"feed": {"entry": []}}])).collect(NOW)
    assert result.events == ()
    assert result.notice == "produto MERRA-2 ainda não disponível"


def merra_granule(time_end="2026-08-03T23:59:59Z"):
    return {
        "id": "G-MERRA",
        "producer_granule_id": "MERRA2_400.tavg1_2d_aer_Nx.20260803.nc4",
        "time_start": "2026-08-03T00:00:00Z",
        "time_end": time_end,
        "links": [{
            "title": "OPeNDAP request URL",
            "href": "https://opendap.earthdata.nasa.gov/fake-merra",
        }],
    }


def merra_dataset(value=0.4, variable="DUEXTTAU"):
    return xr.Dataset(
        {
            variable: (
                ("time", "lat", "lon"),
                [[[value]]],
                {"units": "1"},
            )
        },
        coords={
            "time": [datetime(2026, 8, 3, 23, 30, tzinfo=timezone.utc)],
            "lat": [-20.0],
            "lon": [-15.0],
        },
    )


def merra_result(
    *, value=0.4, variable="DUEXTTAU", time_end="2026-08-03T23:59:59Z",
    configured=None, opener=None,
):
    configured = configured or settings(
        merra2_region_ids=("central_south_atlantic",)
    )
    client = Client([{"feed": {"entry": [merra_granule(time_end)]}}])
    dataset_opener = opener or (lambda url: merra_dataset(value, variable))
    return Merra2Collector(
        configured, client, dataset_opener=dataset_opener
    ).collect(NOW)


def test_merra2_acima_do_threshold():
    result = merra_result(value=0.4)
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "merra2_dust_confirmation"
    assert event.title == "Carga de poeira elevada confirmada pelo MERRA-2"
    assert event.evidence[0]["variable"] == "DUEXTTAU"
    assert event.evidence[0]["value"] == 0.4


def test_merra2_abaixo_do_threshold():
    result = merra_result(value=0.1)
    assert result.events == ()
    assert result.discarded == 1


def test_merra2_latencia_excessiva():
    configured = settings(
        merra2_region_ids=("central_south_atlantic",),
        merra2_max_latency_hours=24,
    )
    result = merra_result(
        configured=configured,
        time_end="2026-08-01T00:00:00Z",
    )
    assert result.events == ()
    assert "latência máxima" in result.notice


def test_merra2_variavel_ausente():
    configured = settings(
        merra2_region_ids=("central_south_atlantic",),
        merra2_variable="DUCMASS",
    )
    result = merra_result(
        configured=configured,
        variable="DUEXTTAU",
    )
    assert result.events == ()
    assert "variável DUCMASS ausente" in result.notice


def test_merra2_erro_autenticacao_sanitizado():
    secret = "senha-earthdata-nao-pode-vazar"

    def fail(url):
        raise RuntimeError(secret)

    result = merra_result(opener=fail)
    assert "autenticação" in result.error
    assert secret not in result.error


def test_merra2_credencial_oficial_ausente(tmp_path):
    configured = settings(
        merra2_region_ids=("central_south_atlantic",)
    )
    client = Client([{"feed": {"entry": [merra_granule()]}}])
    result = Merra2Collector(
        configured,
        client,
        credentials_path=tmp_path / "missing",
    ).collect(NOW)
    assert result.events == ()
    assert result.error == "credencial Earthdata ausente em ~/.netrc"


def test_merra2_idempotencia():
    first = merra_result(value=0.4)
    second = merra_result(value=0.4)
    assert first.events[0].id == second.events[0].id


def test_merra2_evidencia_normalizada():
    evidence = merra_result(value=0.4).events[0].evidence[0]
    required = {
        "source", "collection", "variable", "region", "window_start",
        "window_end", "value", "threshold", "unit", "occurred_at",
        "retrieved_at",
    }
    assert required <= set(evidence)


class FixedCollector:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def collect(self, now):
        if self.error:
            raise self.error
        return self.result


def cams_result(*rows):
    return CamsCollector(settings(), records_loader=lambda now, regions: list(rows)).collect(NOW)


def cmr_result(*rows):
    return CmrCollector(settings(), Client([{"feed": {"entry": []}}, {"feed": {"entry": list(rows)}}])).collect(NOW)


def test_multiplas_fontes_nao_fundidas_sem_regra():
    collectors = {"cams": FixedCollector(cams_result(cams_row())), "cmr": FixedCollector(cmr_result(cmr_row()))}
    run = run_real_signals(settings=settings(), sources=("cams", "cmr"), now=NOW, collectors=collectors)
    assert len(run.events) == 2
    assert len(run.signals) == 2


def test_idempotencia_mesma_entrada():
    result = cams_result(cams_row())
    collectors = {"cams": FixedCollector(result)}
    first = run_real_signals(settings=settings(), sources=("cams",), now=NOW, collectors=collectors)
    second = run_real_signals(settings=settings(), sources=("cams",), now=NOW, collectors=collectors)
    assert [event.id for event in first.events] == [event.id for event in second.events]
    assert [signal.id for signal in first.signals] == [signal.id for signal in second.signals]


def test_duas_regioes_e_duas_janelas():
    rows = [cams_row("central_south_atlantic", valid_time="2026-08-04T06:00:00Z"), cams_row("central_south_atlantic", valid_time="2026-08-04T12:00:00Z"), cams_row("east_south_atlantic")]
    result = cams_result(*rows)
    assert len({event.id for event in result.events}) == len(result.events)
    assert len({event.primary_claim_id for event in result.events if event.category == "dust_transport_forecast"}) == 2


def test_nova_janela_atualiza_mesmo_sinal_agrupado():
    result = cams_result(cams_row(valid_time="2026-08-04T06:00:00Z"), cams_row(valid_time="2026-08-04T12:00:00Z"))
    run = run_real_signals(settings=settings(), sources=("cams",), now=NOW, collectors={"cams": FixedCollector(result)})
    assert len(run.events) == 2
    assert len(run.signals) == 1
    assert len(run.signals[0].member_event_ids) == 2


def test_revisao_granulo_mantem_identidade_do_sinal():
    first_result = cmr_result(cmr_row(updated="2026-08-04T11:00:00Z"))
    second_result = cmr_result(cmr_row(updated="2026-08-04T12:00:00Z"))
    first = run_real_signals(settings=settings(), sources=("cmr",), now=NOW, collectors={"cmr": FixedCollector(first_result)})
    second = run_real_signals(settings=settings(), sources=("cmr",), now=NOW, collectors={"cmr": FixedCollector(second_result)})
    assert first.events[0].id == second.events[0].id
    assert first.signals[0].id == second.signals[0].id


def test_varios_granulos_na_mesma_janela_sao_agregados():
    rows = [
        cmr_row("G1", time_start="2026-08-04T06:10:00Z"),
        cmr_row("G2", time_start="2026-08-04T07:20:00Z"),
        cmr_row("G3", time_start="2026-08-04T11:50:00Z"),
    ]
    result = cmr_result(*rows)
    run = run_real_signals(settings=settings(), sources=("cmr",), now=NOW, collectors={"cmr": FixedCollector(result)})
    assert len(result.events) == 1
    assert len(run.signals) == 1
    evidence = result.events[0].evidence[0]
    assert evidence["granule_count"] == 3
    assert evidence["representative_event_id"] == str(result.events[0].id)
    assert run.signals[0].representative_event_id == evidence["representative_event_id"]
    assert len(evidence["granules"]) == 3
    assert len(run.signals[0].member_event_ids) == 3
    assert evidence["earliest_occurred_at"] == "2026-08-04T06:10:00+00:00"
    assert evidence["latest_occurred_at"] == "2026-08-04T11:50:00+00:00"


def test_granulos_em_janelas_diferentes_nao_sao_agrupados():
    result = cmr_result(
        cmr_row("G1", time_start="2026-08-04T05:59:00Z"),
        cmr_row("G2", time_start="2026-08-04T06:00:00Z"),
    )
    assert len(result.events) == 2
    assert {event.evidence[0]["window_start_utc"] for event in result.events} == {
        "2026-08-04T00:00:00+00:00",
        "2026-08-04T06:00:00+00:00",
    }


def test_colecoes_distintas_nao_sao_agrupadas():
    configured = settings(
        cmr_calipso_collection_ids=(),
        cmr_modis_collection_ids=("COLLECTION-A", "COLLECTION-B"),
    )
    client = Client([
        {"feed": {"entry": [cmr_row("G1")]}},
        {"feed": {"entry": [cmr_row("G2")]}},
    ])
    result = CmrCollector(configured, client).collect(NOW)
    assert len(result.events) == 2
    assert {event.evidence[0]["collection_concept_id"] for event in result.events} == {"COLLECTION-A", "COLLECTION-B"}


def test_regioes_distintas_nao_sao_agrupadas():
    result = cmr_result(
        cmr_row("G1", region="south_atlantic"),
        cmr_row("G2", region="brazil_coast"),
    )
    assert len(result.events) == 2
    assert {event.evidence[0]["region"] for event in result.events} == {"south_atlantic", "brazil_coast"}


def test_revisao_substitui_membro_sem_aumentar_contagem():
    result = cmr_result(
        cmr_row("G1", updated="2026-08-04T10:30:00Z"),
        cmr_row("G1", updated="2026-08-04T11:30:00Z"),
    )
    evidence = result.events[0].evidence[0]
    assert evidence["granule_count"] == 1
    assert evidence["granules"][0]["revision"] == "2026-08-04T11:30:00Z"
    assert result.duplicates == 1


def test_cmr_repetido_e_idempotente():
    result = cmr_result(cmr_row("G1"), cmr_row("G2"))
    collectors = {"cmr": FixedCollector(result)}
    first = run_real_signals(settings=settings(), sources=("cmr",), now=NOW, collectors=collectors)
    second = run_real_signals(settings=settings(), sources=("cmr",), now=NOW, collectors=collectors)
    assert first.events[0].id == second.events[0].id
    assert first.signals[0].id == second.signals[0].id
    assert first.signals[0].member_event_ids == second.signals[0].member_event_ids


def test_titulo_e_resumo_cmr_agregados_e_factuais():
    result = cmr_result(cmr_row("G1"), cmr_row("G2"))
    event = result.events[0]
    assert event.title == "Novos produtos MODIS disponíveis para o Atlântico Sul"
    assert "registrou 2 produtos" in event.summary
    assert "entre 06:00 e 12:00 UTC" in event.summary
    assert "não confirma presença de poeira" in event.summary
    forbidden = ("transporte", "aproximação", "chegada")
    assert not any(term in event.summary.lower() for term in forbidden)


def test_erro_parcial_e_lote_vazio():
    collectors = {"cams": FixedCollector(error=httpx.ConnectError("offline")), "cmr": FixedCollector(CollectionResult(source="cmr"))}
    run = run_real_signals(settings=settings(), sources=("cams", "cmr"), now=NOW, collectors=collectors)
    assert run.events == ()
    assert run.signals == ()
    assert run.collections[0].error == "ConnectError"
    assert run.result.status == "partial"
    assert run.result.partial
    assert run.result.requested_sources == ("cams", "cmr")
    assert run.result.successful_sources == ("cmr",)
    assert run.result.failed_sources == ("cams",)


class Store:
    def __init__(self):
        self.calls = []

    def upsert_many(self, signals):
        self.calls.append(signals)
        return ResearcherSignalStoreResult(received=len(signals), persisted=len(signals), persisted_ids=tuple(signal.id for signal in signals))


def test_persistencia_em_lote():
    store = Store()
    result = cams_result(cams_row("east_south_atlantic"), cams_row("brazil_coast"))
    run = run_real_signals(settings=settings(), sources=("cams",), now=NOW, collectors={"cams": FixedCollector(result)}, store=store)
    assert len(store.calls) == 1
    assert store.calls[0] == run.signals
    assert run.persistence.persisted == len(run.signals)


def test_run_result_complete_partial_e_failed():
    success = FixedCollector(CollectionResult(source="ok"))
    failure = FixedCollector(error=RuntimeError("offline"))

    complete = run_real_signals(
        settings=settings(), sources=("a", "b", "c"), now=NOW,
        collectors={"a": success, "b": success, "c": success},
    )
    partial = run_real_signals(
        settings=settings(), sources=("a", "b", "c"), now=NOW,
        collectors={"a": success, "b": success, "c": failure},
    )
    failed = run_real_signals(
        settings=settings(), sources=("a", "b", "c"), now=NOW,
        collectors={"a": failure, "b": failure, "c": failure},
    )

    assert complete.result.status == "complete"
    assert complete.result.successful_sources == ("a", "b", "c")
    assert complete.result.failed_sources == ()
    assert partial.result.status == "partial"
    assert partial.result.successful_sources == ("a", "b")
    assert partial.result.failed_sources == ("c",)
    assert failed.result.status == "failed"
    assert failed.result.successful_sources == ()
    assert failed.result.failed_sources == ("a", "b", "c")


def test_persistencia_parcial_mantem_sinais_das_fontes_saudaveis():
    store = Store()
    healthy = cams_result(cams_row())
    run = run_real_signals(
        settings=settings(), sources=("cams", "cmr"), now=NOW,
        collectors={
            "cams": FixedCollector(healthy),
            "cmr": FixedCollector(error=RuntimeError("offline")),
        },
        store=store,
    )

    assert run.result.status == "partial"
    assert run.result.signals_persisted == len(run.eligible_signal_ids)
    assert store.calls == [tuple(
        signal for signal in run.signals if signal.id in run.eligible_signal_ids
    )]

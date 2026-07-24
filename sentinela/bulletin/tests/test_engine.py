"""Testes do Bulletin Engine (112.6A) — determinístico, sem banco, sem LLM."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sentinela.bulletin.engine import BulletinEngine, dedup_events, sort_events
from sentinela.bulletin.models import BulletinModel
from sentinela.core.models import EpistemicStatus, Event, PipelineStatus

NOW = datetime.now(timezone.utc)


def ev(title="t", *, area=None, cat=None, conf=0.5, review=False, occurred=None,
       claim_id=None, status=EpistemicStatus.HYPOTHESIS, validated=None):
    return Event(id=uuid4(), primary_claim_id=claim_id, title=title,
                 epistemic_status=status, confidence_score=conf,
                 category=cat, scientific_area=area,
                 requires_human_review=review, occurred_at=occurred,
                 validated_at=validated or NOW,
                 pipeline_status=PipelineStatus.VALIDATED)


# ---------------- ordenação ----------------
def test_ordena_review_por_ultimo():
    e = sort_events([ev("a", review=True), ev("b", review=False)])
    assert [x.title for x in e] == ["b", "a"]


def test_ordena_confidence_desc_nulls_last():
    e = sort_events([ev("baixa", conf=0.3), ev("nula", conf=None), ev("alta", conf=0.9)])
    assert [x.title for x in e] == ["alta", "baixa", "nula"]


def test_ordena_occurred_desc_nulls_last():
    e = sort_events([
        ev("velho", conf=0.5, occurred=NOW - timedelta(days=5)),
        ev("sem_data", conf=0.5, occurred=None),
        ev("novo", conf=0.5, occurred=NOW),
    ])
    assert [x.title for x in e] == ["novo", "velho", "sem_data"]


# ---------------- deduplicação ----------------
def test_dedup_por_claim_id():
    cid = uuid4()
    out = dedup_events([ev("a", claim_id=cid), ev("b", claim_id=cid)])
    assert len(out) == 1 and out[0][1] == 2       # 1 item, source_count=2


def test_dedup_por_titulo_normalizado_e_categoria():
    a = ev("Estudo Sobre o Clima!", cat="climate")
    b = ev("estudo sobre o clima", cat="climate")   # acento/pontuação/caixa
    out = dedup_events([a, b])
    assert len(out) == 1 and out[0][1] == 2


def test_dedup_nao_colapsa_categorias_diferentes():
    a = ev("mesmo titulo", cat="climate")
    b = ev("mesmo titulo", cat="geoscience")
    assert len(dedup_events([a, b])) == 2


# ---------------- agrupamento ----------------
def test_agrupa_por_scientific_area():
    m = BulletinEngine().build([ev("x", area="climatology"), ev("y", area="climatology")])
    assert len(m.sections) == 1 and m.sections[0].title == "climatology"
    assert len(m.sections[0].items) == 2


def test_fallback_category_depois_outros():
    m = BulletinEngine().build([
        ev("com_area", area="oceanography"),
        ev("so_categoria", cat="climate"),
        ev("nada"),
    ])
    titles = [s.title for s in m.sections]
    assert "oceanography" in titles and "climate" in titles and "outros" in titles


# ---------------- contrato ----------------
def test_build_produz_bulletinmodel_valido():
    m = BulletinEngine().build([ev("a", area="climate", conf=0.8)])
    assert isinstance(m, BulletinModel)
    BulletinModel.model_validate(m.model_dump())     # revalida no Pydantic
    assert m.total_items == 1


def test_requires_review_preservado():
    """Evento validado mas que exige curadoria continua no boletim, marcado."""
    m = BulletinEngine().build([ev("precisa_revisao", area="clima", review=True)])
    item = m.sections[0].items[0]
    assert item.requires_review is True             # engine não decide publicar


def test_engine_nao_toca_banco_nem_llm():
    import inspect
    import sentinela.bulletin.engine as mod
    src = inspect.getsource(mod)
    assert "psycopg" not in src and "LLMClient" not in src and "openrouter" not in src.lower()


def test_deterministico():
    evs = [ev("a", conf=0.9, area="x"), ev("b", conf=0.5, area="x"), ev("c", conf=0.7, area="y")]
    m1 = BulletinEngine().build(list(evs))
    m2 = BulletinEngine().build(list(reversed(evs)))
    def shape(m): return [(s.title, [i.title for i in s.items]) for s in m.sections]
    # mesma entrada (conjunto) → mesma organização, independente da ordem de chegada
    assert sorted(shape(m1)) == sorted(shape(m2))

from decimal import Decimal

from sentinela.seismic_editorial.engine import _depth, _location, _magnitude


def test_normalizacao_numerica_aprovada():
    assert _magnitude(Decimal("5.3")) == "5,3"
    assert _depth(Decimal("66.312")) == ("66,3", True)
    assert _depth(Decimal("145.679")) == ("145,7", True)
    assert _depth(Decimal("10.0")) == ("10", False)


def test_normalizacao_geografica_sarangani():
    location = _location("11 km S of Sarangani, Philippines")
    assert location is not None
    assert location.title_phrase == "ao sul de Sarangani, nas Filipinas"
    assert location.precise_phrase == "cerca de 11 km ao sul de Sarangani, nas Filipinas"


def test_normalizacao_geografica_macquarie():
    location = _location("west of Macquarie Island")
    assert location is not None
    assert location.title_phrase == "na região da Ilha Macquarie"
    assert location.precise_phrase == "a oeste da Ilha Macquarie"


def test_normalizacao_geografica_kermadec():
    location = _location("Kermadec Islands region")
    assert location is not None
    assert location.precise_phrase == "na região das Ilhas Kermadec"


def test_normalizacao_geografica_leste_sudeste():
    location = _location("3 km ESE of Gambiran Satu, Indonesia")
    assert location is not None
    assert location.title_phrase == "próximo a Gambiran Satu, na Indonésia"
    assert location.precise_phrase == (
        "cerca de 3 km a leste-sudeste de Gambiran Satu, na Indonésia"
    )


def test_normalizacao_geografica_sul_sudoeste_papua_nova_guine():
    location = _location("45 km SSW of Angoram, Papua New Guinea")
    assert location is not None
    assert location.title_phrase == "próximo a Angoram, em Papua-Nova Guiné"
    assert location.precise_phrase == (
        "cerca de 45 km ao sul-sudoeste de Angoram, em Papua-Nova Guiné"
    )
    assert location.keywords == ("Angoram", "Papua-Nova Guiné")


def test_normalizacao_geografica_leste_nordeste_filipinas():
    location = _location("22 km ENE of Lapuan, Philippines")
    assert location is not None
    assert location.title_phrase == "próximo a Lapuan, nas Filipinas"
    assert location.precise_phrase == (
        "cerca de 22 km a leste-nordeste de Lapuan, nas Filipinas"
    )
    assert location.keywords == ("Lapuan", "Filipinas")


def test_normalizacao_geografica_preserva_severo_kurilsk():
    location = _location("222 km SSW of Severo-Kuril’sk, Russia")
    assert location is not None
    assert location.title_phrase == "ao sul-sudoeste de Severo-Kuril’sk, na Rússia"
    assert location.precise_phrase == (
        "cerca de 222 km ao sul-sudoeste de Severo-Kuril’sk, na Rússia"
    )
    assert location.keywords == ("Severo-Kuril’sk", "Rússia")


def test_local_nao_autorizado_e_preservado_literalmente():
    location = _location("42 km NW of Example")
    assert location is not None
    assert location.title_phrase == (
        'com localização informada como "42 km NW of Example"'
    )
    assert location.keywords == ()
    assert "noroeste" not in location.precise_phrase

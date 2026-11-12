from datetime import date

import pytest

from microrredes.analises.fundamentais import AnaliseFundamental, PerfilConsumo
from microrredes.dados.tarifas_aneel import TarifaSnapshot


@pytest.fixture
def snapshot() -> TarifaSnapshot:
    return TarifaSnapshot(
        distribuidora="TESTE",
        grupo="A4",
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=None,
        fonte="teste",
        consultado_em_utc="2026-10-05T00:00:00+00:00",
        registros_consultados=1,
        azul={
            "tusd_ponta_demanda": 10.0,
            "tusd_fora_ponta_demanda": 5.0,
            "tusd_ponta_consumo": 0.2,
            "tusd_fora_ponta_consumo": 0.1,
            "te_ponta": 0.3,
            "te_fora_ponta": 0.2,
        },
        verde={
            "tusd_demanda": 7.0,
            "tusd_ponta_consumo": 0.2,
            "tusd_fora_ponta_consumo": 0.1,
            "te_ponta": 0.4,
            "te_fora_ponta": 0.2,
        },
    )


def test_icms_e_aplicado_por_gross_up(snapshot: TarifaSnapshot) -> None:
    perfil = PerfilConsumo(100, 200, 50, 80)
    resultado = AnaliseFundamental(snapshot, icms=0.20).custo_azul(perfil)

    consumo_sem_icms = 100 * 0.5 + 200 * 0.3
    assert resultado["consumo_sem_icms"] == pytest.approx(consumo_sem_icms)
    assert resultado["consumo_com_icms"] == pytest.approx(consumo_sem_icms / 0.8)
    assert resultado["custo_total"] == pytest.approx(resultado["consumo_com_icms"] + 50 * 10 + 80 * 5)


def test_comparacao_retorna_modalidade_e_fonte(snapshot: TarifaSnapshot) -> None:
    resultado = AnaliseFundamental(snapshot).comparar_modalidades(PerfilConsumo(100, 200, 50, 80))

    assert resultado["melhor_modalidade"] in {"azul", "verde"}
    assert resultado["fonte_tarifas"]["fonte"] == "teste"


def test_perfil_rejeita_valor_negativo() -> None:
    with pytest.raises(ValueError):
        PerfilConsumo(-1, 0, 0, 0)

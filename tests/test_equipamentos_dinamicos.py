import pytest

from Equipamentos.bess import BESS, ParametrosBESS
from Equipamentos.gerador_diesel import GeradorDiesel, ParametrosGeradorDiesel


def test_gerador_expoe_equacoes_diferenciais_e_responde_a_degrau():
    modelo = GeradorDiesel(ParametrosGeradorDiesel())
    modelo.inicializar(carga_inicial_kw=100.0)
    modelo.estado.frequencia_hz = 59.5

    derivadas = modelo.equacoes_diferenciais(
        potencia_eletrica_kw=200.0,
        tensao_comando_pu=1.0,
        potencia_referencia_kw=100.0,
    )

    assert derivadas["d_potencia_governador_dt_kw_s"] > 0
    assert derivadas["d_frequencia_dt_hz_s"] < 0
    estado = modelo.passo(0.01, 200.0, 1.0, potencia_referencia_kw=100.0)
    assert estado.frequencia_hz < 60.0
    assert len(modelo.historico) == 1


def test_bess_tem_classe_propria_e_equacao_de_soc_com_sinal_consistente():
    bess = BESS(ParametrosBESS(capacidade_kwh=100.0, soc_inicial=0.5))
    soc_inicial = bess.estado.soc

    estado_descarga = bess.passo_potencia(1.0, 40.0)
    assert estado_descarga.soc < soc_inicial
    assert estado_descarga.potencia_kw == pytest.approx(40.0)
    assert bess.equacao_diferencial_soc(40.0) < 0

    soc_apos_descarga = estado_descarga.soc
    estado_carga = bess.passo_potencia(1.0, -40.0)
    assert estado_carga.soc > soc_apos_descarga
    assert bess.equacao_diferencial_soc(-40.0) > 0


def test_bess_limita_soc_e_aceita_acoes_legadas():
    bess = BESS(ParametrosBESS(soc_inicial=0.9, soc_maximo=0.9))

    estado = bess.passo_acao(1.0, "carregar", 1000.0)
    assert estado.soc == pytest.approx(0.9)
    assert estado.potencia_kw == pytest.approx(0.0)

    estado = bess.passo_acao(1.0, "descarregar", 10.0)
    assert estado.potencia_kw == pytest.approx(10.0)

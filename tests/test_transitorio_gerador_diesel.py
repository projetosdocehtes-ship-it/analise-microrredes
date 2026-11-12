import json
from pathlib import Path

import pytest

from microrredes.analises.transitorio_gerador_diesel import (
    ConfiguracaoGeradorDiesel,
    ConfiguracaoTransitorioDiesel,
    EventoGeradorDiesel,
    TransitorioGeradorDiesel,
)


ROOT = Path(__file__).resolve().parents[1]
ENTRADA = ROOT / "Entradas" / "Entradas_transitorio_gerador_diesel.json"
ENTRADA_LEGADA = ROOT / "Entradas" / "gerador_diesel_teste.json"


def test_configuracao_separa_diesel_e_rejeita_passo_instavel():
    gerador = ConfiguracaoGeradorDiesel()

    with pytest.raises(ValueError, match="no máximo 1/5"):
        ConfiguracaoTransitorioDiesel(gerador=gerador, passo_s=0.2)


def test_pandapower_gen_carrega_parametros_de_curto_circuito():
    simulacao = TransitorioGeradorDiesel(ConfiguracaoTransitorioDiesel())

    net, indices = simulacao.montar_rede_pandapower()
    linha_gen = net.gen.loc[indices["indice_gen"]]

    assert linha_gen["type"] == "sync"
    assert linha_gen["xdss_pu"] == pytest.approx(0.20)
    assert linha_gen["rdss_ohm"] == pytest.approx(0.01)
    assert net.converged

    curto = simulacao.calcular_curto_circuito()
    assert curto["fault"] == "3ph"
    assert curto["ikss_ka"] > 0
    assert curto["skss_mva"] > 0


def test_transitorio_offgrid_responde_a_degrau_e_curto():
    configuracao = ConfiguracaoTransitorioDiesel(
        duracao_s=6.0,
        eventos=(
            EventoGeradorDiesel("degrau_carga", inicio_s=1.0, carga_kw=200.0),
            EventoGeradorDiesel("curto_circuito_3ph", inicio_s=3.0, duracao_s=0.15),
        ),
    )

    resultado = TransitorioGeradorDiesel(configuracao).executar()
    serie = resultado["serie_temporal"]
    durante_degrau = next(item for item in serie if item["tempo_s"] == 1.0)
    durante_curto = next(item for item in serie if item["tempo_s"] == 3.0)

    assert resultado["modo"] == "offgrid"
    assert resultado["resumo"]["passos"] == 601
    assert resultado["resumo"]["passos_com_degrau_carga"] > 0
    assert durante_degrau["carga_kw"] == pytest.approx(200.0)
    assert durante_curto["curto_circuito_ativo"] is True
    assert durante_curto["corrente_curto_ka"] > 0
    assert resultado["resumo"]["tensao_min_pu"] < 0.8
    assert resultado["resumo"]["frequencia_min_hz"] < 60.0


def test_configuracao_json_e_saida_sao_reprodutiveis(tmp_path):
    configuracao = ConfiguracaoTransitorioDiesel.from_json(ENTRADA)
    resultado = TransitorioGeradorDiesel(configuracao).executar()
    saida = tmp_path / "diesel.json"
    saida.write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
    reaberto = json.loads(saida.read_text(encoding="utf-8"))

    assert configuracao.gerador.id_gerador == "Diesel_Teste_1"
    assert len(configuracao.eventos) == 2
    assert reaberto["tipo_analise"] == "transitorio_gerador_diesel_reduzido"
    assert reaberto["pandapower"]["elemento"] == "gen"


def test_configuracao_legada_continua_aceita():
    configuracao = ConfiguracaoTransitorioDiesel.from_json(ENTRADA_LEGADA)

    assert configuracao.gerador.id_gerador == "Diesel_Teste_1"
    assert configuracao.passo_s == 0.01
    assert configuracao.duracao_s == 6.0
    assert len(configuracao.eventos) == 2

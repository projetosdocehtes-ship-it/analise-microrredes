import json
from pathlib import Path

import pytest

from microrredes.analises.falhas import AnaliseFalhas
from microrredes.analises.fluxo_potencia import AnaliseFluxoPotencia, DependenciaOpcionalAusente


ROOT = Path(__file__).resolve().parents[1]


def test_fluxo_demo_converge():
    resultado = AnaliseFluxoPotencia().executar_demo()
    assert resultado["analise"] == "fluxo_potencia"
    assert resultado["convergiu"] is True
    assert resultado["tensoes_pu"]


def test_curto_circuito_e_independente_do_fluxo():
    resultado = AnaliseFalhas().executar_demo(tipo="3ph")
    assert resultado["analise"] == "curto_circuito"
    assert resultado["barras_avaliadas"] >= 1
    assert all(valor > 0 for valor in resultado["corrente_inicial_simetrica_ka"].values())


def test_tipo_de_falha_invalido_e_rejeitado():
    with pytest.raises(ValueError):
        AnaliseFalhas().executar_demo(tipo="invalido")


def test_fluxo_carrega_arquivo_entradas_proprio_e_isolado(tmp_path):
    base = {
        "nome_projeto": "Estudo permanente teste",
        "conectado_rede": True,
        "painel_info": [{"pv_id": "PV_1", "Pmp": 610, "quantidade": [10, 1]}],
        "inversor_info": [{"inv_id": "Inv_1", "Out_Pmax": 38.5, "Eficiencia": 0.98, "quantidade": 1}],
        "cargas_info": [{"carga_id": "Load_1", "s_instalada": 12000, "fp": 0.95, "quantidade": 1}],
        "bateria_info": [],
        "barramento_info": [{"bus_id": "Bus_ac_1", "V_linha_nominal": 380}],
        "geradordiesel_info": [],
        "grafo_conexoes": [
            {"between": ["PV_1", "Inv_1"]},
            {"between": ["Inv_1", "Bus_ac_1"]},
            {"between": ["Bus_ac_1", "Load_1"]},
        ],
    }
    entrada_a = tmp_path / "permanente_a.json"
    entrada_b = tmp_path / "permanente_b.json"
    entrada_a.write_text(json.dumps(base), encoding="utf-8")
    base["cargas_info"][0]["s_instalada"] = 24000
    entrada_b.write_text(json.dumps(base), encoding="utf-8")

    analise = AnaliseFluxoPotencia()
    resultado_a = analise.executar_arquivo(entrada_a)
    resultado_b = analise.executar_arquivo(entrada_b)

    assert resultado_a["convergiu"] is True
    assert resultado_b["convergiu"] is True
    assert resultado_a["arquivo_entrada"] != resultado_b["arquivo_entrada"]
    assert resultado_a["tensoes_pu"] != resultado_b["tensoes_pu"]


def test_fluxo_entrada_ilhada_exige_fonte_de_referencia(tmp_path):
    entrada = tmp_path / "ilhada.json"
    entrada.write_text(
        json.dumps(
            {
                "conectado_rede": False,
                "cargas_info": [{"carga_id": "Load_1", "s_instalada": 1000, "fp": 1}],
                "barramento_info": [{"bus_id": "Bus_ac_1", "V_linha_nominal": 380}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gerador diesel"):
        AnaliseFluxoPotencia().executar_arquivo(entrada)


def test_entrada_diesel_popula_gen_do_pandapower_e_permite_curto():
    entrada = ROOT / "Entradas" / "Entradas_regime_permanente_diesel.json"
    analise = AnaliseFluxoPotencia()
    net, metadados = analise.criar_rede_entrada(entrada)

    resultado = analise.executar(net)
    gerador = net.gen.iloc[0]
    curto = AnaliseFalhas().executar(net, tipo="3ph", caso="max")

    assert resultado["convergiu"] is True
    assert gerador["name"] == "Diesel_1"
    assert gerador["type"] == "sync"
    assert gerador["sn_mva"] == pytest.approx(0.34375)
    assert gerador["vn_kv"] == pytest.approx(0.38)
    assert gerador["xdss_pu"] == pytest.approx(0.20)
    assert gerador["rdss_ohm"] == pytest.approx(0.01)
    assert metadados["parametros_gerador_diesel_pandapower"]["cos_phi"] == pytest.approx(0.8)
    assert curto["barras_avaliadas"] >= 1
    assert all(valor > 0 for valor in curto["corrente_inicial_simetrica_ka"].values())


def test_entrada_diesel_conectado_tambem_usa_gen_sincrono(tmp_path):
    documento = json.loads(
        (ROOT / "Entradas" / "Entradas_regime_permanente_diesel.json").read_text(encoding="utf-8")
    )
    documento["conectado_rede"] = True
    entrada = tmp_path / "diesel_on_grid.json"
    entrada.write_text(json.dumps(documento), encoding="utf-8")

    analise = AnaliseFluxoPotencia()
    net, _ = analise.criar_rede_entrada(entrada)
    resultado = analise.executar(net)
    curto = AnaliseFalhas().executar(net, tipo="3ph", caso="max")

    assert resultado["convergiu"] is True
    assert len(net.gen) == 1
    assert not bool(net.gen.iloc[0]["slack"])
    assert net.gen.iloc[0]["type"] == "sync"
    assert curto["barras_avaliadas"] >= 1

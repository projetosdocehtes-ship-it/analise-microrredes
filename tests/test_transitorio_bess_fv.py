import json
from pathlib import Path

import pytest

from microrredes.analises.transitorio_bess_fv import ConfiguracaoTransitorio, TransitorioBessFV
from microrredes.analises.graficos_interativos import gerar_html_interativo


ROOT = Path(__file__).resolve().parents[1]
ENTRADA_MICRORREDE = ROOT / "Entradas" / "Entradas_microrrede_completa.json"
ENTRADA_LIGACAO_DIESEL = ROOT / "Entradas" / "Entradas_transitorio_diesel_ligacao_rede.json"


def _entrada(tmp_path):
    caminho = tmp_path / "Entradas.Json"
    caminho.write_text(json.dumps({
        "conectado_rede": False,
        "Config_Simulacao": [{"Tipo_Sim": "Transiente", "Passo_sim": 0.001, "Tempo_sim": 1.0}],
        "Falhas_sim": [{
            "Tipo_Falha": "Perda_String_FV",
            "id_pv": "PV_1",
            "T_falha": [0.5],
            "duracao_falha": [0.25],
            "strings_totais": [16],
            "strings_perdidas": [4],
        }],
    }), encoding="utf-8")
    return caminho


def test_transitorio_liga_aplica_falha_e_retorna_on_grid(tmp_path):
    resultado = TransitorioBessFV(ConfiguracaoTransitorio(
        entrada=_entrada(tmp_path),
        forcar_on_grid=True,
    )).executar()

    assert resultado["parametros"]["conectado_rede_simulacao"] is True
    assert resultado["contingencia"]["inicio_s"] == pytest.approx(0.5)
    assert resultado["contingencia"]["fim_s"] == pytest.approx(0.75)
    assert len(resultado["serie_temporal"]["tempo_s"]) == 1000
    assert max(resultado["serie_temporal"]["pv_kw"]) > 0
    assert resultado["resumo"]["pcc_tensao_min_pu"] > 0.94


def test_transitorio_gera_graficos(tmp_path):
    resultado = TransitorioBessFV(ConfiguracaoTransitorio(entrada=_entrada(tmp_path))).executar()
    arquivos = TransitorioBessFV.gerar_graficos(resultado, tmp_path / "graficos")

    assert {arquivo.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for arquivo in arquivos} == {
        "transitorio_potencias_soc.png",
        "transitorio_pcc.png",
    }
    assert all((tmp_path / "graficos" / nome).stat().st_size > 0 for nome in {
        "transitorio_potencias_soc.png",
        "transitorio_pcc.png",
    })


def test_transitorio_interativo_preserva_todos_os_passos_e_funciona_offline(tmp_path):
    resultado = TransitorioBessFV(ConfiguracaoTransitorio(entrada=_entrada(tmp_path))).executar()
    arquivo = gerar_html_interativo(resultado, tmp_path / "transitorio_interativo.html")
    html = (tmp_path / "transitorio_interativo.html").read_text(encoding="utf-8")

    assert arquivo.endswith("transitorio_interativo.html")
    assert '"n":1000' in html
    assert '"inicio_falha_s":0.5' in html
    assert '"fim_falha_s":0.75' in html
    assert "pointermove" in html
    assert "<script src=" not in html


def test_entrada_unica_conecta_pv_bess_e_diesel_no_transitorio():
    resultado = TransitorioBessFV(
        ConfiguracaoTransitorio(entrada=ENTRADA_MICRORREDE)
    ).executar()

    assert resultado["tipo_analise"] == "transitorio_reduzido_microrrede_com_diesel"
    assert resultado["modelo"] == "PV+BESS+GeradorDiesel"
    assert resultado["resumo"]["passos"] == 600
    assert resultado["resumo"]["passos_com_degrau_carga"] > 0
    assert resultado["resumo"]["diesel_potencia_max_kw"] > 0
    assert resultado["resumo"]["frequencia_min_hz"] < 60.0
    assert resultado["resumo"]["pcc_tensao_min_pu"] == 0.12
    assert resultado["pandapower"]["rede_entrada"]["fluxo_inicial"]["convergiu"] is True
    assert resultado["pandapower"]["curto_circuito_inicial_do_ensaio"]["ikss_ka"] > 0


def test_gerador_entra_em_paralelo_com_rede_no_instante_configurado():
    resultado = TransitorioBessFV(
        ConfiguracaoTransitorio(entrada=ENTRADA_LIGACAO_DIESEL)
    ).executar()
    serie = resultado["serie_temporal"]
    tempos = serie["tempo_s"]
    indice_antes = max(i for i, tempo in enumerate(tempos) if tempo < 0.1)
    indice_ligacao = min(i for i, tempo in enumerate(tempos) if tempo >= 0.1)

    assert resultado["tempo_ligacao_gerador_s"] == pytest.approx(0.1)
    assert serie["gerador_ligado"][indice_antes] == 0
    assert serie["gerador_ligado"][indice_ligacao] == 1
    assert serie["rede_kw"][indice_antes] > 0.0
    assert serie["diesel_kw"][indice_antes] == pytest.approx(0.0)
    assert serie["diesel_kw"][indice_ligacao] > 0.0
    assert serie["potencia_mecanica_diesel_kw"][indice_ligacao] < serie["diesel_kw"][indice_ligacao]
    assert resultado["pandapower"]["rede_entrada"]["fluxo_inicial"]["convergiu"] is True

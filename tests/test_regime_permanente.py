import json
from pathlib import Path

import pytest

from microrredes.analises.regime_permanente import (
    ConfiguracaoRegimePermanente,
    ErroPerfilCarga,
    PerfilCargaHoraria,
    RegimePermanente,
)


ROOT = Path(__file__).resolve().parents[1]
ENTRADA_EXEMPLO = ROOT / "Entradas" / "Entradas_regime_permanente.json"
ENTRADA_DIESEL = ROOT / "Entradas" / "Entradas_regime_permanente_diesel.json"
ENTRADA_MICRORREDE = ROOT / "Entradas" / "Entradas_microrrede_completa.json"
CURVA_EXEMPLO = ROOT / "Entradas" / "perfil_carga_regime_permanente.csv"


def test_perfil_carga_legado_carrega_os_dois_tipos_de_dia():
    perfil = PerfilCargaHoraria(CURVA_EXEMPLO)

    assert perfil.demanda(0, "util") == 4.0
    assert perfil.demanda(0, "fim_semana") == 3.5
    assert perfil.estatisticas()["util"]["energia_diaria_kwh"] == 161.9


def test_perfil_carga_rejeita_curva_incompleta(tmp_path):
    curva = tmp_path / "curva_incompleta.csv"
    curva.write_text("hora,demanda_kw,dia_semana\n0,1,util\n", encoding="utf-8")

    try:
        PerfilCargaHoraria(curva)
    except ErroPerfilCarga as exc:
        assert "exatamente uma demanda" in str(exc)
    else:
        raise AssertionError("A curva incompleta deveria ser rejeitada")


def test_timeline_anual_gera_8760_horas_e_bissexto_8784():
    anual = RegimePermanente.gerar_timeline(
        ConfiguracaoRegimePermanente(entrada=ENTRADA_EXEMPLO, periodo="ano", ano=2025)
    )
    bissexto = RegimePermanente.gerar_timeline(
        ConfiguracaoRegimePermanente(entrada=ENTRADA_EXEMPLO, periodo="ano", ano=2024)
    )

    assert len(anual) == 8760
    assert len(bissexto) == 8784
    assert anual[0].year == 2025
    assert anual[-1].hour == 23


def test_regime_permanente_24h_usa_curva_e_converge():
    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=ENTRADA_EXEMPLO,
            periodo="24h",
            tipo_dia="fim_semana",
        )
    ).executar()

    assert resultado["analise"] == "regime_permanente_horario"
    assert resultado["resumo"]["horas_simuladas"] == 24
    assert resultado["resumo"]["horas_convergidas"] == 24
    assert resultado["passos_horarios"][0]["demanda_kw"] == 3.5
    assert resultado["passos_horarios"][12]["demanda_kw"] == 7.0


def test_regime_permanente_offgrid_com_diesel_bess_e_pv():
    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=ENTRADA_DIESEL,
            periodo="24h",
            tipo_dia="util",
        )
    ).executar()

    assert resultado["rede"]["conectado_rede"] is False
    assert resultado["resumo"]["horas_convergidas"] == 24
    assert max(passo["diesel_kw"] for passo in resultado["passos_horarios"]) > 0
    assert resultado["resumo"]["horas_com_deficit"] == 0


def test_mesmo_arquivo_da_microrrede_completa_roda_no_permanente():
    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=ENTRADA_MICRORREDE,
            periodo="24h",
            tipo_dia="util",
        )
    ).executar()

    assert resultado["resumo"]["horas_convergidas"] == 24
    assert max(passo["diesel_kw"] for passo in resultado["passos_horarios"]) > 0


def test_configuracao_do_regime_e_lida_do_arquivo_unico():
    configuracao = ConfiguracaoRegimePermanente.from_entrada(ENTRADA_MICRORREDE)

    assert configuracao.periodo == "24h"
    assert configuracao.tipo_dia == "util"
    assert configuracao.ano == 2025
    assert configuracao.horas == 24


def test_curva_carga_pode_ser_sobrescrita_por_arquivo_proprio(tmp_path):
    documento = json.loads(ENTRADA_EXEMPLO.read_text(encoding="utf-8"))
    entrada = tmp_path / "entrada.json"
    curva = tmp_path / "curva.csv"
    entrada.write_text(json.dumps(documento), encoding="utf-8")
    curva.write_text(
        "hora,demanda_kw,dia_semana\n"
        + "".join(f"{hora},1,util\n" for hora in range(24))
        + "".join(f"{hora},2,fim_semana\n" for hora in range(24)),
        encoding="utf-8",
    )

    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=entrada,
            curva_carga=curva,
            periodo="24h",
            tipo_dia="util",
            horas=2,
        )
    ).executar()

    assert resultado["arquivo_curva_carga"] == str(curva.resolve())
    assert [passo["demanda_kw"] for passo in resultado["passos_horarios"]] == [1.0, 1.0]


def test_regime_permanente_calcula_custo_do_diesel_e_capex_opcional(tmp_path):
    documento = json.loads(ENTRADA_DIESEL.read_text(encoding="utf-8"))
    documento["cargas_info"][0]["curva_carga"] = str(CURVA_EXEMPLO)
    diesel = documento["geradordiesel_info"][0]
    diesel.update(
        {
            "custo_diesel_litro": 6.50,
            "consumo_diesel_l_kwh": 0.25,
            "custo_equipamento": 360000.0,
        }
    )
    entrada = tmp_path / "diesel_economia.json"
    entrada.write_text(json.dumps(documento), encoding="utf-8")

    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=entrada,
            periodo="24h",
            tipo_dia="util",
            horas=4,
        )
    ).executar()

    economia = resultado["analise_economica"]
    energia_diesel = economia["energia_diesel_kwh"]
    assert energia_diesel > 0.0
    assert economia["consumo_oleo_diesel_litros"] == pytest.approx(energia_diesel * 0.25)
    assert economia["custo_oleo_diesel"] == pytest.approx(energia_diesel * 0.25 * 6.50)
    assert economia["custo_equipamento"] == pytest.approx(360000.0)
    assert economia["custo_total_periodo"] == pytest.approx(
        economia["custo_oleo_diesel"] + economia["custo_equipamento"]
    )
    assert economia["custo_equipamento_considerado"] is True
    assert economia["equipamento_existente"] is False


def test_tempo_de_operacao_do_gerador_limita_despacho_e_custo(tmp_path):
    documento = json.loads(ENTRADA_DIESEL.read_text(encoding="utf-8"))
    documento["cargas_info"][0]["curva_carga"] = str(CURVA_EXEMPLO)
    documento["geradordiesel_info"][0].update(
        {
            "custo_diesel_litro": 6.50,
            "consumo_diesel_l_kwh": 0.25,
            "custo_investimento": 0.0,
        }
    )
    entrada = tmp_path / "diesel_horas.json"
    entrada.write_text(json.dumps(documento), encoding="utf-8")

    resultado = RegimePermanente(
        ConfiguracaoRegimePermanente(
            entrada=entrada,
            periodo="24h",
            tipo_dia="util",
            horas=4,
            tempo_operacao_gerador_h=1,
        )
    ).executar()

    economia = resultado["analise_economica"]
    assert economia["tempo_operacao_gerador_configurado_h"] == 1.0
    assert economia["horas_operacao_gerador_h"] == 1.0
    assert sum(passo["diesel_kw"] > 0 for passo in resultado["passos_horarios"]) == 1
    assert resultado["resumo"]["horas_com_deficit"] > 0
    assert economia["custo_equipamento"] == 0.0
    assert economia["equipamento_existente"] is True

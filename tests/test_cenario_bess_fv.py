import pytest

from microrredes.analises.cenario_bess_fv import ConfiguracaoCenario, CenarioBessFV


def test_cenario_on_grid_conserva_consumo_e_mede_contingencia():
    resultado = CenarioBessFV().executar()
    base = resultado["caso_base"]
    contingencia = resultado["caso_contingencia"]

    assert base["energia_carga_kwh"] == pytest.approx(650.0)
    assert base["rede_conectada_em_todos_os_passos"] is True
    assert contingencia["energia_pv_perdida_kwh"] > 0
    assert contingencia["energia_pv_disponivel_kwh"] < base["energia_pv_disponivel_kwh"]
    assert resultado["impacto_contingencia"]["delta_energia_pv_disponivel_kwh"] < 0


def test_configuracao_rejeita_perda_de_strings_invalida():
    with pytest.raises(ValueError):
        ConfiguracaoCenario(strings_fv=4, strings_perdidas=5)


def test_gera_graficos_horarios(tmp_path):
    resultado = CenarioBessFV().executar()

    arquivos = CenarioBessFV.gerar_graficos(resultado, tmp_path)

    assert {arquivo.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for arquivo in arquivos} == {
        "regime_permanente_bess_fv.png",
        "contingencia_strings_fv.png",
    }
    assert all((tmp_path / nome).stat().st_size > 0 for nome in {
        "regime_permanente_bess_fv.png",
        "contingencia_strings_fv.png",
    })

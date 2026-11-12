import requests

from microrredes.dados.tarifas_aneel import ClienteTarifasANEEL, TarifaSnapshot


def test_normaliza_registros_aneel_por_modalidade_e_unidade() -> None:
    registros = [
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Azul",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "200,00",
            "VlrTE": "300,00",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Azul",
            "DscDetalhe": "Demanda",
            "NomPostoTarifario": "Ponta",
            "DscUnidadeTerciaria": "R$/kW",
            "VlrTUSD": "40,00",
            "VlrTE": "0",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Demanda",
            "NomPostoTarifario": "Não se aplica",
            "DscUnidadeTerciaria": "R$/kW",
            "VlrTUSD": "20,00",
            "VlrTE": "0",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Fora ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "100,00",
            "VlrTE": "200,00",
        },
    ]

    snapshot = TarifaSnapshot.de_registros(registros, "TESTE", "A4")

    assert snapshot.azul["tusd_ponta_consumo"] == 0.2
    assert snapshot.azul["te_ponta"] == 0.3
    assert snapshot.azul["tusd_ponta_demanda"] == 40.0
    assert snapshot.verde["tusd_demanda"] == 20.0
    assert snapshot.verde["te_fora_ponta"] == 0.2


class _Resposta:
    def __init__(self, registros):
        self.registros = registros

    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True, "result": {"records": self.registros}}


class _Sessao:
    def __init__(self, registros):
        self.registros = registros

    def get(self, *_args, **_kwargs):
        return _Resposta(self.registros)


def test_cliente_seleciona_vigencia_mais_recente_sem_rede_real(tmp_path) -> None:
    registros = [
        {
            "DatInicioVigencia": "2025-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Demanda",
            "NomPostoTarifario": "Não se aplica",
            "DscUnidadeTerciaria": "R$/kW",
            "VlrTUSD": "10",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Demanda",
            "NomPostoTarifario": "Não se aplica",
            "DscUnidadeTerciaria": "R$/kW",
            "VlrTUSD": "20",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "100",
            "VlrTE": "200",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Verde",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Fora ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "100",
            "VlrTE": "200",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Azul",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "100",
            "VlrTE": "200",
        },
        {
            "DatInicioVigencia": "2026-01-01",
            "DscSubGrupo": "A4",
            "DscBaseTarifaria": "Tarifa de Aplicação",
            "DscModalidadeTarifaria": "Azul",
            "DscDetalhe": "Não se aplica",
            "NomPostoTarifario": "Fora ponta",
            "DscUnidadeTerciaria": "R$/MWh",
            "VlrTUSD": "100",
            "VlrTE": "200",
        },
    ]
    cliente = ClienteTarifasANEEL(
        "TESTE",
        session=_Sessao(registros),
        cache_path=tmp_path / "tarifas_aneel_cache.json",
        permitir_fallback=False,
    )

    snapshot = cliente.carregar()

    assert snapshot.vigencia_inicio.isoformat() == "2026-01-01"
    assert snapshot.verde["tusd_demanda"] == 20.0


class _RespostaCsv:
    content = (
        "DatInicioVigencia;DatFimVigencia;DscBaseTarifaria;SigAgente;DscSubGrupo;"
        "DscModalidadeTarifaria;DscDetalhe;NomPostoTarifario;DscUnidadeTerciaria;VlrTUSD;VlrTE\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Verde;Demanda;Não se aplica;R$/kW;20;0\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Verde;Não se aplica;Ponta;R$/MWh;100;200\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Verde;Não se aplica;Fora ponta;R$/MWh;100;200\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Azul;Não se aplica;Ponta;R$/MWh;100;200\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Azul;Não se aplica;Fora ponta;R$/MWh;100;200\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Azul;Demanda;Ponta;R$/kW;20;0\n"
        "2026-01-01;;Tarifa de Aplicação;TESTE;A4;Azul;Demanda;Fora ponta;R$/kW;20;0\n"
    ).encode("utf-8")

    def raise_for_status(self):
        return None


class _SessaoCsv:
    def get(self, url, **_kwargs):
        if "datastore_search" in url:
            raise requests.ConnectionError("API CKAN indisponível no teste")
        return _RespostaCsv()


def test_cliente_tem_fallback_para_csv_oficial(tmp_path) -> None:
    cliente = ClienteTarifasANEEL(
        "TESTE",
        session=_SessaoCsv(),
        cache_path=tmp_path / "tarifas_aneel_cache.json",
        permitir_fallback=False,
    )

    snapshot = cliente.carregar()

    assert snapshot.fonte == "ANEEL_CSV"
    assert snapshot.verde["tusd_demanda"] == 20.0
    assert snapshot.verde["te_ponta"] == 0.2


class _SessaoIndisponivel:
    def get(self, *_args, **_kwargs):
        raise requests.ConnectionError("ANEEL indisponível no teste")


def test_cliente_persiste_e_reutiliza_cache_quando_aneel_falha(tmp_path) -> None:
    cache = tmp_path / "tarifas_aneel_cache.json"
    online = ClienteTarifasANEEL("TESTE", session=_SessaoCsv(), cache_path=cache)
    snapshot_online = online.carregar()

    offline = ClienteTarifasANEEL("TESTE", session=_SessaoIndisponivel(), cache_path=cache)
    snapshot_cache = offline.carregar()

    assert cache.exists()
    assert snapshot_online.fonte == "ANEEL_CSV"
    assert snapshot_cache.fonte == "ANEEL_CACHE"
    assert snapshot_cache.modo_acesso == "cache"
    assert snapshot_cache.verde["te_fora_ponta"] == 0.2

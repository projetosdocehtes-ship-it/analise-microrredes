"""Simulação horária de regime permanente a partir de JSON e curva CSV."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .fluxo_potencia import AnaliseFluxoPotencia, _importar_pandapower


SOLAR_PROFILE = tuple(
    max(math.sin((hora - 6) * math.pi / 12.0), 0.0) if 6 <= hora < 18 else 0.0
    for hora in range(24)
)
CONSUMO_ESPECIFICO_DIESEL_PADRAO_L_KWH = 0.25


class ErroPerfilCarga(ValueError):
    """Indica que a curva horária não atende ao contrato do estudo."""


@dataclass(frozen=True)
class ConfiguracaoRegimePermanente:
    """Parâmetros de execução do estudo horário."""

    entrada: str | Path
    periodo: str = "24h"
    tipo_dia: str = "util"
    ano: int = 2025
    horas: int | None = None
    curva_carga: str | Path | None = None
    escala_carga: float | None = None
    dia_semana: int | None = None
    tempo_operacao_gerador_h: float | None = None

    @classmethod
    def from_entrada(cls, entrada: str | Path) -> "ConfiguracaoRegimePermanente":
        """Lê a configuração de regime permanente embutida no mesmo JSON."""

        caminho = Path(entrada).expanduser().resolve()
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo de entrada não encontrado: {caminho}")
        try:
            documento = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de entrada inválido: {caminho}") from exc
        estudo = _configuracao_regime_embutida(documento)
        return cls(
            entrada=entrada,
            periodo=estudo.get("periodo", "24h"),
            tipo_dia=estudo.get("tipo_dia", "util"),
            ano=int(estudo.get("ano", 2025)),
            horas=int(estudo["horas"]) if estudo.get("horas") is not None else None,
            curva_carga=estudo.get("curva_carga"),
            escala_carga=float(estudo["escala_carga"]) if estudo.get("escala_carga") is not None else None,
            dia_semana=int(estudo["dia_semana"]) if estudo.get("dia_semana") is not None else None,
            tempo_operacao_gerador_h=(
                float(estudo["tempo_operacao_gerador_h"])
                if estudo.get("tempo_operacao_gerador_h") is not None
                else None
            ),
        )

    def __post_init__(self) -> None:
        if self.periodo not in {"24h", "ano"}:
            raise ValueError("periodo deve ser '24h' ou 'ano'")
        if self.tipo_dia not in {"util", "fim_semana"}:
            raise ValueError("tipo_dia deve ser 'util' ou 'fim_semana'")
        if self.ano < 1:
            raise ValueError("ano deve ser positivo")
        if self.horas is not None and self.horas <= 0:
            raise ValueError("horas deve ser positivo")
        if self.periodo == "24h" and self.horas is not None and self.horas > 24:
            raise ValueError("horas não pode exceder 24 no periodo 24h")
        if self.dia_semana is not None and not 0 <= self.dia_semana <= 6:
            raise ValueError("dia_semana deve estar entre 0 e 6")
        if self.escala_carga is not None and self.escala_carga <= 0:
            raise ValueError("escala_carga deve ser positiva")
        if self.tempo_operacao_gerador_h is not None:
            if self.tempo_operacao_gerador_h < 0:
                raise ValueError("tempo_operacao_gerador_h não pode ser negativo")
            if not self.tempo_operacao_gerador_h.is_integer():
                raise ValueError("tempo_operacao_gerador_h deve ser inteiro, pois o passo é de 1 hora")


class PerfilCargaHoraria:
    """Carrega e consulta a curva legada ``hora,demanda_kw,dia_semana``."""

    COLUNAS = {"hora", "demanda_kw", "dia_semana"}
    TIPOS = ("util", "fim_semana")

    def __init__(self, arquivo: str | Path, escala: float = 1.0) -> None:
        self.arquivo = Path(arquivo).expanduser().resolve()
        self.escala = float(escala)
        if self.escala <= 0:
            raise ErroPerfilCarga("A escala da curva deve ser positiva")
        if not self.arquivo.is_file():
            raise FileNotFoundError(f"Arquivo de curva de carga não encontrado: {self.arquivo}")
        try:
            dados = pd.read_csv(self.arquivo)
        except (OSError, pd.errors.ParserError) as exc:
            raise ErroPerfilCarga(f"Não foi possível ler a curva de carga: {self.arquivo}") from exc
        dados.columns = [str(coluna).strip().lower() for coluna in dados.columns]
        faltantes = self.COLUNAS.difference(dados.columns)
        if faltantes:
            raise ErroPerfilCarga(f"Curva de carga sem colunas obrigatórias: {sorted(faltantes)}")

        dados = dados[["hora", "demanda_kw", "dia_semana"]].copy()
        dados["hora"] = pd.to_numeric(dados["hora"], errors="coerce")
        dados["demanda_kw"] = pd.to_numeric(dados["demanda_kw"], errors="coerce")
        if dados[["hora", "demanda_kw"]].isna().any().any():
            raise ErroPerfilCarga("hora e demanda_kw devem ser numéricos")
        if (dados["hora"] % 1 != 0).any():
            raise ErroPerfilCarga("hora deve conter valores inteiros")
        dados["hora"] = dados["hora"].astype(int)
        if not dados["hora"].between(0, 23).all():
            raise ErroPerfilCarga("hora deve estar entre 0 e 23")
        if (dados["demanda_kw"] < 0).any():
            raise ErroPerfilCarga("demanda_kw não pode ser negativa")

        dados["dia_semana"] = (
            dados["dia_semana"].astype(str).str.strip().str.lower()
            .replace({
                "dia_util": "util",
                "dia útil": "util",
                "weekday": "util",
                "fim de semana": "fim_semana",
                "fim-de-semana": "fim_semana",
                "weekend": "fim_semana",
            })
        )
        desconhecidos = sorted(set(dados["dia_semana"]) - set(self.TIPOS))
        if desconhecidos:
            raise ErroPerfilCarga(f"dia_semana contém valores inválidos: {desconhecidos}")

        self._perfis: dict[str, dict[int, float]] = {}
        for tipo in self.TIPOS:
            perfil = dados[dados["dia_semana"] == tipo]
            if len(perfil) != 24 or set(perfil["hora"]) != set(range(24)):
                raise ErroPerfilCarga(
                    f"O perfil '{tipo}' deve possuir exatamente uma demanda para cada hora de 0 a 23"
                )
            if perfil["hora"].duplicated().any():
                raise ErroPerfilCarga(f"O perfil '{tipo}' possui horas duplicadas")
            self._perfis[tipo] = {
                int(linha.hora): float(linha.demanda_kw) * self.escala
                for linha in perfil.itertuples(index=False)
            }

    def demanda(self, hora: int, tipo_dia: str) -> float:
        if not 0 <= hora <= 23:
            raise ValueError("hora deve estar entre 0 e 23")
        if tipo_dia not in self.TIPOS:
            raise ValueError("tipo_dia deve ser 'util' ou 'fim_semana'")
        return self._perfis[tipo_dia][hora]

    def energia_diaria(self, tipo_dia: str) -> float:
        return sum(self._perfis[tipo_dia].values())

    def estatisticas(self) -> dict[str, dict[str, float]]:
        return {
            tipo: {
                "demanda_media_kw": sum(perfil.values()) / 24.0,
                "demanda_pico_kw": max(perfil.values()),
                "demanda_minima_kw": min(perfil.values()),
                "energia_diaria_kwh": sum(perfil.values()),
                "fator_carga": sum(perfil.values()) / (24.0 * max(perfil.values())) if max(perfil.values()) else 0.0,
            }
            for tipo, perfil in self._perfis.items()
        }


@dataclass(frozen=True)
class _ParametrosOperacao:
    fator_potencia: float
    pv_kwp: float
    eficiencia_inversor: float
    pv_max_kw: float | None
    bess_kwh: float
    bess_kw_carga: float
    bess_kw_descarga: float
    soc_inicial: float
    soc_minimo: float
    soc_maximo: float
    eficiencia_carga: float
    eficiencia_descarga: float
    permite_carga: bool
    permite_descarga: bool
    janela_carga: tuple[int, int]
    janela_descarga: tuple[int, int]
    diesel_kw: float
    diesel_quantidade: int
    diesel_custo_oleo_diesel_por_litro: float
    diesel_consumo_especifico_litros_por_kwh: float
    diesel_custo_equipamento_por_unidade: float
    diesel_custo_equipamento_total: float
    diesel_tempo_operacao_h: float | None


class RegimePermanente:
    """Executa um fluxo de potência AC a cada hora do horizonte escolhido."""

    def __init__(self, configuracao: ConfiguracaoRegimePermanente) -> None:
        self.configuracao = configuracao

    def executar(self) -> dict[str, Any]:
        configuracao = self.configuracao
        entrada = Path(configuracao.entrada).expanduser().resolve()
        documento = self._ler_json(entrada)
        carga = _primeiro(documento, "cargas_info")
        caminho_curva = self._resolver_curva(entrada, carga)
        escala = configuracao.escala_carga
        if escala is None:
            escala = _numero(carga.get("fator_escala_curva"), 1.0)
        perfil = PerfilCargaHoraria(caminho_curva, escala=escala)
        parametros = self._parametros(documento, configuracao.tempo_operacao_gerador_h)
        timeline = self.gerar_timeline(configuracao)
        net, metadados_rede = AnaliseFluxoPotencia.criar_rede_entrada(entrada)
        indices = self._indices_rede(net, documento)
        if not indices["load"]:
            raise ValueError("A rede de entrada precisa possuir pelo menos uma carga")
        if not documento.get("conectado_rede", True) and not indices["gen"]:
            raise ValueError("A simulação ilhada precisa possuir um gerador de referência")

        soc_kwh = parametros.bess_kwh * parametros.soc_inicial / 100.0
        passos: list[dict[str, Any]] = []
        horas_operacao_gerador = 0.0
        for instante in timeline:
            tipo_dia = "util" if instante.weekday() < 5 else "fim_semana"
            if configuracao.periodo == "24h":
                tipo_dia = configuracao.tipo_dia
            demanda_kw = perfil.demanda(instante.hour, tipo_dia)
            pv_bruta_kw = parametros.pv_kwp * SOLAR_PROFILE[instante.hour]
            pv_kw = pv_bruta_kw * parametros.eficiencia_inversor
            if parametros.pv_max_kw is not None:
                pv_kw = min(pv_kw, parametros.pv_max_kw)

            bateria_kw, soc_kwh = self._despachar_bateria(
                parametros,
                hora=instante.hour,
                pv_kw=pv_kw,
                demanda_kw=demanda_kw,
                soc_kwh=soc_kwh,
            )
            saldo_sem_diesel_kw = demanda_kw - pv_kw - bateria_kw
            conectado_rede = bool(documento.get("conectado_rede", True))
            diesel_kw = 0.0
            deficit_kw = 0.0
            curtailment_kw = 0.0
            if not conectado_rede:
                pode_operar = (
                    parametros.diesel_tempo_operacao_h is None
                    or horas_operacao_gerador < parametros.diesel_tempo_operacao_h
                )
                if pode_operar:
                    diesel_kw = min(max(saldo_sem_diesel_kw, 0.0), parametros.diesel_kw)
                deficit_kw = max(saldo_sem_diesel_kw - diesel_kw, 0.0)
                curtailment_kw = max(-saldo_sem_diesel_kw, 0.0)
                rede_kw = 0.0
            else:
                rede_kw = saldo_sem_diesel_kw

            horas_operacao_passo = 1.0 if diesel_kw > 0.0 else 0.0
            horas_operacao_gerador += horas_operacao_passo
            consumo_oleo_diesel_litros = (
                diesel_kw * parametros.diesel_consumo_especifico_litros_por_kwh
            )
            custo_oleo_diesel = (
                consumo_oleo_diesel_litros * parametros.diesel_custo_oleo_diesel_por_litro
            )

            self._atualizar_rede(net, indices, parametros, demanda_kw, pv_kw, bateria_kw, diesel_kw)
            passo = self._resolver_hora(
                net=net,
                indices=indices,
                instante=instante,
                demanda_kw=demanda_kw,
                pv_bruta_kw=pv_bruta_kw,
                pv_kw=pv_kw,
                bateria_kw=bateria_kw,
                diesel_kw=diesel_kw,
                rede_kw=rede_kw,
                soc_kwh=soc_kwh,
                deficit_kw=deficit_kw,
                curtailment_kw=curtailment_kw,
                horas_operacao_gerador_h=horas_operacao_passo,
                consumo_oleo_diesel_litros=consumo_oleo_diesel_litros,
                custo_oleo_diesel=custo_oleo_diesel,
            )
            passos.append(passo)

        return {
            "analise": "regime_permanente_horario",
            "arquivo_entrada": str(entrada),
            "arquivo_curva_carga": str(caminho_curva),
            "configuracao": asdict(configuracao),
            "rede": metadados_rede,
            "perfil_carga": {
                "escala": escala,
                "estatisticas": perfil.estatisticas(),
            },
            "premissas": {
                "passo_horas": 1.0,
                "perfil_solar": "curva senoidal fixa entre 06:00 e 18:00",
                "convencao_rede_kw": "positivo importa; negativo exporta",
                "convencao_bateria_kw": "positivo descarrega; negativo carrega",
                "soc_continua_no_horizonte": configuracao.periodo == "ano",
                "tempo_operacao_gerador_h": (
                    "limite acumulado no horizonte; nulo significa sem limite"
                ),
            },
            "resumo": self._resumo(passos, parametros),
            "analise_economica": self._analise_economica(passos, parametros),
            "passos_horarios": passos,
        }

    @staticmethod
    def gerar_timeline(configuracao: ConfiguracaoRegimePermanente) -> list[datetime]:
        if configuracao.periodo == "24h":
            weekday = configuracao.dia_semana
            if weekday is None:
                weekday = 0 if configuracao.tipo_dia == "util" else 6
            inicio = datetime(configuracao.ano, 1, 1)
            while inicio.weekday() != weekday:
                inicio += timedelta(days=1)
            total = configuracao.horas or 24
        else:
            inicio = datetime(configuracao.ano, 1, 1)
            total = (datetime(configuracao.ano + 1, 1, 1) - inicio).days * 24
            if configuracao.horas is not None:
                total = min(total, configuracao.horas)
        return [inicio + timedelta(hours=hora) for hora in range(total)]

    @staticmethod
    def _ler_json(entrada: Path) -> dict[str, Any]:
        if not entrada.is_file():
            raise FileNotFoundError(f"Arquivo de entrada não encontrado: {entrada}")
        try:
            documento = json.loads(entrada.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de entrada inválido: {entrada}") from exc
        if not isinstance(documento, dict):
            raise ValueError("O arquivo de entrada deve conter um objeto JSON")
        return documento

    def _resolver_curva(self, entrada: Path, carga: dict[str, Any]) -> Path:
        caminho = self.configuracao.curva_carga or carga.get("curva_carga")
        if not caminho:
            raise ValueError("Informe cargas_info.curva_carga ou --curva-carga")
        caminho = Path(caminho).expanduser()
        if not caminho.is_absolute():
            caminho = entrada.parent / caminho
        return caminho.resolve()

    @staticmethod
    def _parametros(
        documento: dict[str, Any], tempo_operacao_override: float | None = None
    ) -> _ParametrosOperacao:
        painel = _primeiro(documento, "painel_info")
        inversor = _primeiro(documento, "inversor_info")
        carga = _primeiro(documento, "cargas_info")
        bateria = _primeiro(documento, "bateria_info")
        diesel = _primeiro(documento, "geradordiesel_info")

        fp = _numero(carga.get("fp"), 0.95)
        if not 0 < fp <= 1:
            raise ValueError("fp da carga deve estar entre zero e um")
        eficiencia = _numero(inversor.get("Eficiencia"), 1.0)
        if not 0 < eficiencia <= 1:
            raise ValueError("Eficiencia do inversor deve estar entre zero e um")
        pv_kwp = _numero(painel.get("Pmp"), 0.0) * _quantidade(painel.get("quantidade", 1)) / 1000.0
        pv_max_kw = _numero(inversor.get("Out_Pmax"), None)
        if pv_max_kw is not None:
            pv_max_kw *= _quantidade(inversor.get("quantidade", 1))

        if not bateria:
            bess_kwh = bess_carga = bess_descarga = 0.0
            soc_inicial = soc_minimo = soc_maximo = 0.0
            eficiencia_carga = eficiencia_descarga = 1.0
            permite_carga = permite_descarga = False
            janela_carga = janela_descarga = (0, 0)
        else:
            quantidade = _quantidade(bateria.get("quantidade", 1))
            bess_kwh = _numero(bateria.get("capacidade_kwh"), 0.0) * quantidade
            bess_carga = _numero(bateria.get("potencia_max_carga_kw"), 0.0) * quantidade
            bess_descarga = _numero(bateria.get("potencia_max_descarga_kw"), 0.0) * quantidade
            soc_inicial = _numero(bateria.get("soc_inicial"), 50.0)
            soc_minimo = _numero(bateria.get("soc_min"), 0.0)
            soc_maximo = _numero(bateria.get("soc_max"), 100.0)
            eficiencia_carga = _numero(bateria.get("eficiencia_carga"), 1.0)
            eficiencia_descarga = _numero(bateria.get("eficiencia_descarga"), 1.0)
            periodo_carga = bateria.get("periodo_de_carga") or {}
            periodo_descarga = bateria.get("periodo_de_descarga") or {}
            permite_carga = bool(periodo_carga.get("permitir_carga", True))
            permite_descarga = bool(periodo_descarga.get("permitir_descarga", True))
            janela_carga = _janela(periodo_carga.get("horario_carga_permitido", "00:00-24:00"))
            janela_descarga = _janela(periodo_descarga.get("horario_descarga_permitido", "18:00-21:00"))
            if not 0 <= soc_minimo <= soc_inicial <= soc_maximo <= 100:
                raise ValueError("soc_min, soc_inicial e soc_max devem estar entre 0 e 100")
            if not 0 < eficiencia_carga <= 1 or not 0 < eficiencia_descarga <= 1:
                raise ValueError("eficiências da bateria devem estar entre zero e um")

        diesel_quantidade = _quantidade(diesel.get("quantidade", 1)) if diesel else 0
        custo_oleo = _numero(
            _primeiro_valor(
                diesel,
                "custo_oleo_diesel_por_litro",
                "custo_oleo_diesel_litro",
                "custo_oleo_diesel",
                "custo_diesel_litro",
                "custo_diesel",
                "preco_oleo_diesel_litro",
                "preco_diesel_litro",
            ),
            0.0,
        )
        consumo_especifico = _numero(
            _primeiro_valor(
                diesel,
                "consumo_especifico_litros_por_kwh",
                "consumo_diesel_l_kwh",
                "consumo_oleo_diesel_litros_por_kwh",
                "consumo_combustivel_litros_por_kwh",
                "consumo_especifico",
            ),
            CONSUMO_ESPECIFICO_DIESEL_PADRAO_L_KWH,
        )
        custo_equipamento = _numero(
            _primeiro_valor(
                diesel,
                "custo_equipamento",
                "custo_investimento",
                "custo_investimento_diesel",
            ),
            0.0,
        )
        operacao = diesel.get("operacao") if isinstance(diesel.get("operacao"), dict) else {}
        tempo_operacao_bloco = _primeiro_valor(
            operacao,
            "tempo_operacao_h",
            "tempo_operacao_gerador_h",
            "horas_operacao",
        )
        if tempo_operacao_bloco is None:
            tempo_operacao_bloco = _primeiro_valor(
                diesel,
                "tempo_operacao_h",
                "tempo_operacao_gerador_h",
                "horas_operacao",
            )
        tempo_operacao_configurado = (
            tempo_operacao_override
            if tempo_operacao_override is not None
            else tempo_operacao_bloco
        )
        tempo_operacao = (
            None
            if tempo_operacao_configurado is None or tempo_operacao_configurado == ""
            else _numero(tempo_operacao_configurado, None)
        )
        for nome, valor in (
            ("custo_oleo_diesel_por_litro", custo_oleo),
            ("consumo_especifico_litros_por_kwh", consumo_especifico),
            ("custo_equipamento", custo_equipamento),
        ):
            if not math.isfinite(valor) or valor < 0:
                raise ValueError(f"{nome} não pode ser negativo")
        if tempo_operacao is not None:
            if tempo_operacao < 0:
                raise ValueError("tempo_operacao_h não pode ser negativo")
            if not tempo_operacao.is_integer():
                raise ValueError("tempo_operacao_h deve ser inteiro, pois o passo é de 1 hora")

        potencia_diesel = max(
            _numero(diesel.get("potencia_nominal_kw"), 0.0) * diesel_quantidade,
            0.0,
        )
        return _ParametrosOperacao(
            fator_potencia=fp,
            pv_kwp=max(pv_kwp, 0.0),
            eficiencia_inversor=eficiencia,
            pv_max_kw=pv_max_kw,
            bess_kwh=max(bess_kwh, 0.0),
            bess_kw_carga=max(bess_carga, 0.0),
            bess_kw_descarga=max(bess_descarga, 0.0),
            soc_inicial=soc_inicial,
            soc_minimo=soc_minimo,
            soc_maximo=soc_maximo,
            eficiencia_carga=eficiencia_carga,
            eficiencia_descarga=eficiencia_descarga,
            permite_carga=permite_carga,
            permite_descarga=permite_descarga,
            janela_carga=janela_carga,
            janela_descarga=janela_descarga,
            diesel_kw=potencia_diesel,
            diesel_quantidade=diesel_quantidade,
            diesel_custo_oleo_diesel_por_litro=custo_oleo,
            diesel_consumo_especifico_litros_por_kwh=consumo_especifico,
            diesel_custo_equipamento_por_unidade=custo_equipamento,
            diesel_custo_equipamento_total=custo_equipamento * diesel_quantidade,
            diesel_tempo_operacao_h=tempo_operacao,
        )

    @staticmethod
    def _indices_rede(net: Any, documento: dict[str, Any]) -> dict[str, list[int] | int | None]:
        painel = _primeiro(documento, "painel_info")
        bateria = _primeiro(documento, "bateria_info")
        diesel = _primeiro(documento, "geradordiesel_info")
        nomes_pv = {str(painel.get("pv_id"))} if painel.get("pv_id") else set()
        nomes_bess = {str(bateria.get("bateria_id"))} if bateria.get("bateria_id") else set()
        nomes_diesel = {str(diesel.get("diesel_id"))} if diesel.get("diesel_id") else set()
        pv = [int(idx) for idx, row in net.sgen.iterrows() if str(row.get("name")) in nomes_pv]
        bess = [int(idx) for idx, row in net.sgen.iterrows() if str(row.get("name")) in nomes_bess]
        diesel_sgen = [int(idx) for idx, row in net.sgen.iterrows() if str(row.get("name")) in nomes_diesel]
        diesel_gen = [int(idx) for idx, row in net.gen.iterrows() if str(row.get("name")) in nomes_diesel]
        pcc_id = str((_primeiro(documento, "barramento_info")).get("bus_id") or "Bus_ac_1")
        pcc = next((int(idx) for idx, row in net.bus.iterrows() if str(row.get("name")) == pcc_id), 0)
        return {
            "load": [int(idx) for idx in net.load.index],
            "pv": pv,
            "bess": bess,
            "diesel_sgen": diesel_sgen,
            "gen": diesel_gen,
            "pcc": pcc,
        }

    @staticmethod
    def _despachar_bateria(
        parametros: _ParametrosOperacao,
        hora: int,
        pv_kw: float,
        demanda_kw: float,
        soc_kwh: float,
    ) -> tuple[float, float]:
        if parametros.bess_kwh <= 0:
            return 0.0, 0.0
        soc_min = parametros.bess_kwh * parametros.soc_minimo / 100.0
        soc_max = parametros.bess_kwh * parametros.soc_maximo / 100.0
        if pv_kw > demanda_kw and parametros.permite_carga and _janela_ativa(hora, parametros.janela_carga):
            excedente = pv_kw - demanda_kw
            limite_soc = max((soc_max - soc_kwh) / parametros.eficiencia_carga, 0.0)
            potencia = min(parametros.bess_kw_carga, excedente, limite_soc)
            return -potencia, min(soc_kwh + potencia * parametros.eficiencia_carga, soc_max)
        if demanda_kw > pv_kw and parametros.permite_descarga and _janela_ativa(hora, parametros.janela_descarga):
            deficit = demanda_kw - pv_kw
            limite_soc = max((soc_kwh - soc_min) * parametros.eficiencia_descarga, 0.0)
            potencia = min(parametros.bess_kw_descarga, deficit, limite_soc)
            return potencia, max(soc_kwh - potencia / parametros.eficiencia_descarga, soc_min)
        return 0.0, soc_kwh

    @staticmethod
    def _atualizar_rede(
        net: Any,
        indices: dict[str, list[int] | int | None],
        parametros: _ParametrosOperacao,
        demanda_kw: float,
        pv_kw: float,
        bateria_kw: float,
        diesel_kw: float,
    ) -> None:
        load_idx = indices["load"][0]
        net.load.at[load_idx, "p_mw"] = demanda_kw / 1000.0
        net.load.at[load_idx, "q_mvar"] = demanda_kw * math.tan(math.acos(parametros.fator_potencia)) / 1000.0
        for idx in indices["pv"]:
            net.sgen.at[idx, "p_mw"] = pv_kw / 1000.0 / max(len(indices["pv"]), 1)
            net.sgen.at[idx, "q_mvar"] = 0.0
        for idx in indices["bess"]:
            net.sgen.at[idx, "p_mw"] = bateria_kw / 1000.0 / max(len(indices["bess"]), 1)
            net.sgen.at[idx, "q_mvar"] = 0.0
        for idx in indices["diesel_sgen"]:
            net.sgen.at[idx, "p_mw"] = diesel_kw / 1000.0 / max(len(indices["diesel_sgen"]), 1)
            net.sgen.at[idx, "q_mvar"] = 0.0
        for idx in indices["gen"]:
            net.gen.at[idx, "p_mw"] = diesel_kw / 1000.0 / max(len(indices["gen"]), 1)

    @staticmethod
    def _resolver_hora(
        net: Any,
        indices: dict[str, list[int] | int | None],
        instante: datetime,
        demanda_kw: float,
        pv_bruta_kw: float,
        pv_kw: float,
        bateria_kw: float,
        diesel_kw: float,
        rede_kw: float,
        soc_kwh: float,
        deficit_kw: float,
        curtailment_kw: float,
        horas_operacao_gerador_h: float,
        consumo_oleo_diesel_litros: float,
        custo_oleo_diesel: float,
    ) -> dict[str, Any]:
        pp = _importar_pandapower()
        passo: dict[str, Any] = {
            "timestamp": instante.isoformat(timespec="hours"),
            "hora": instante.hour,
            "dia_semana": instante.weekday(),
            "tipo_dia": "util" if instante.weekday() < 5 else "fim_semana",
            "demanda_kw": round(demanda_kw, 6),
            "pv_bruta_kw": round(pv_bruta_kw, 6),
            "pv_kw": round(pv_kw, 6),
            "bateria_kw": round(bateria_kw, 6),
            "diesel_kw": round(diesel_kw, 6),
            "horas_operacao_gerador_h": round(horas_operacao_gerador_h, 6),
            "consumo_oleo_diesel_litros": round(consumo_oleo_diesel_litros, 6),
            "custo_oleo_diesel": round(custo_oleo_diesel, 6),
            "rede_kw": round(rede_kw, 6),
            "soc_kwh": round(soc_kwh, 6),
            "deficit_kw": round(deficit_kw, 6),
            "curtailment_kw": round(curtailment_kw, 6),
            "convergiu": False,
            "tensao_pu_pcc": None,
            "carregamento_maximo_linha_percentual": None,
            "corrente_maxima_linha_ka": None,
        }
        try:
            pp.runpp(net, algorithm="nr", calculate_voltage_angles=False, numba=False)
            passo["convergiu"] = bool(getattr(net, "converged", False))
            passo["tensao_pu_pcc"] = _arredondar(net.res_bus.vm_pu.at[indices["pcc"]])
            if not net.res_line.empty:
                passo["carregamento_maximo_linha_percentual"] = _arredondar(net.res_line.loading_percent.max())
                passo["corrente_maxima_linha_ka"] = _arredondar(net.res_line.i_ka.max())
            if not net.res_ext_grid.empty:
                passo["rede_pandapower_kw"] = _arredondar(net.res_ext_grid.p_mw.sum() * 1000.0)
            else:
                passo["rede_pandapower_kw"] = 0.0
        except Exception as exc:  # pandapower expõe exceções específicas por algoritmo/rede
            passo["erro"] = str(exc)
        return passo

    @staticmethod
    def _resumo(passos: list[dict[str, Any]], parametros: _ParametrosOperacao) -> dict[str, Any]:
        convergidos = [passo for passo in passos if passo["convergiu"]]
        rede = [passo["rede_kw"] for passo in passos]
        return {
            "horas_simuladas": len(passos),
            "horas_convergidas": len(convergidos),
            "horas_nao_convergidas": len(passos) - len(convergidos),
            "energia_carga_kwh": round(sum(passo["demanda_kw"] for passo in passos), 6),
            "energia_pv_kwh": round(sum(passo["pv_kw"] for passo in passos), 6),
            "energia_bateria_carga_kwh": round(sum(max(-passo["bateria_kw"], 0.0) for passo in passos), 6),
            "energia_bateria_descarga_kwh": round(sum(max(passo["bateria_kw"], 0.0) for passo in passos), 6),
            "energia_importada_rede_kwh": round(sum(max(valor, 0.0) for valor in rede), 6),
            "energia_exportada_rede_kwh": round(sum(max(-valor, 0.0) for valor in rede), 6),
            "energia_deficit_kwh": round(sum(passo["deficit_kw"] for passo in passos), 6),
            "energia_curtailment_kwh": round(sum(passo["curtailment_kw"] for passo in passos), 6),
            "pico_importacao_rede_kw": round(max([max(rede), 0.0]), 6) if rede else 0.0,
            "pico_exportacao_rede_kw": round(abs(min([min(rede), 0.0])), 6) if rede else 0.0,
            "soc_inicial_kwh": round(parametros.bess_kwh * parametros.soc_inicial / 100.0, 6),
            "soc_final_kwh": passos[-1]["soc_kwh"] if passos else 0.0,
            "tensao_minima_pu": min((p["tensao_pu_pcc"] for p in convergidos if p["tensao_pu_pcc"] is not None), default=None),
            "tensao_maxima_pu": max((p["tensao_pu_pcc"] for p in convergidos if p["tensao_pu_pcc"] is not None), default=None),
            "carregamento_maximo_linha_percentual": max((p["carregamento_maximo_linha_percentual"] for p in convergidos if p["carregamento_maximo_linha_percentual"] is not None), default=None),
            "horas_com_deficit": sum(1 for passo in passos if passo["deficit_kw"] > 0),
            "erros": [passo["erro"] for passo in passos if passo.get("erro")],
        }

    @staticmethod
    def _analise_economica(
        passos: list[dict[str, Any]], parametros: _ParametrosOperacao
    ) -> dict[str, Any]:
        """Calcula os custos do diesel no horizonte efetivamente simulado.

        O custo do equipamento é um CAPEX único informado por grupo. Portanto,
        ele fica separado do custo operacional e só entra em
        ``custo_total_periodo`` quando for maior que zero. Valor zero significa
        que o grupo já existe e não deve ser contabilizado no estudo.
        """

        energia_diesel_kwh = sum(passo["diesel_kw"] for passo in passos)
        horas_operacao = sum(passo["horas_operacao_gerador_h"] for passo in passos)
        consumo_litros = sum(passo["consumo_oleo_diesel_litros"] for passo in passos)
        custo_combustivel = sum(passo["custo_oleo_diesel"] for passo in passos)
        custo_equipamento = parametros.diesel_custo_equipamento_total
        custo_total = custo_combustivel + custo_equipamento
        return {
            "moeda": "BRL",
            "horizonte_simulado_h": len(passos),
            "tempo_operacao_gerador_configurado_h": parametros.diesel_tempo_operacao_h,
            "horas_operacao_gerador_h": round(horas_operacao, 6),
            "energia_diesel_kwh": round(energia_diesel_kwh, 6),
            "consumo_especifico_litros_por_kwh": round(
                parametros.diesel_consumo_especifico_litros_por_kwh, 6
            ),
            "consumo_oleo_diesel_litros": round(consumo_litros, 6),
            "custo_oleo_diesel_por_litro": round(
                parametros.diesel_custo_oleo_diesel_por_litro, 6
            ),
            "custo_combustivel_periodo": round(custo_combustivel, 6),
            "custo_oleo_diesel": round(custo_combustivel, 6),
            "custo_diesel": round(custo_combustivel, 6),
            "custo_equipamento_por_unidade": round(
                parametros.diesel_custo_equipamento_por_unidade, 6
            ),
            "custo_equipamento": round(custo_equipamento, 6),
            "quantidade_equipamentos": parametros.diesel_quantidade,
            "gerador_diesel_configurado": parametros.diesel_quantidade > 0,
            "equipamento_existente": (
                parametros.diesel_quantidade > 0 and custo_equipamento == 0.0
            ),
            "custo_equipamento_considerado": custo_equipamento > 0.0,
            "custo_operacional_periodo": round(custo_combustivel, 6),
            "custo_total_periodo": round(custo_total, 6),
            "custo_total": round(custo_total, 6),
            "custo_combustivel_por_kwh_diesel": round(
                custo_combustivel / energia_diesel_kwh, 6
            )
            if energia_diesel_kwh > 0
            else 0.0,
            "custo_total_por_kwh_diesel": round(custo_total / energia_diesel_kwh, 6)
            if energia_diesel_kwh > 0
            else 0.0,
        }


def _primeiro(documento: dict[str, Any], chave: str) -> dict[str, Any]:
    registros = documento.get(chave) or []
    if not isinstance(registros, list):
        raise ValueError(f"{chave} deve ser uma lista de registros")
    if not registros:
        return {}
    if not isinstance(registros[0], dict):
        raise ValueError(f"{chave}[0] deve ser um objeto")
    return registros[0]


def _configuracao_regime_embutida(documento: dict[str, Any]) -> dict[str, Any]:
    estudos = documento.get("estudos") or {}
    if isinstance(estudos, dict) and isinstance(estudos.get("regime_permanente"), dict):
        return _normalizar_configuracao_regime(estudos["regime_permanente"])
    configuracao_dedicada = documento.get("Config_Regime_Permanente")
    if isinstance(configuracao_dedicada, dict):
        return _normalizar_configuracao_regime(configuracao_dedicada)
    configuracoes = documento.get("Config_Simulacao") or []
    if isinstance(configuracoes, dict):
        configuracoes = [configuracoes]
    if isinstance(configuracoes, list):
        for configuracao in configuracoes:
            if not isinstance(configuracao, dict):
                continue
            tipo = str(configuracao.get("Tipo_Sim", "")).lower()
            if "perman" in tipo or "regime" in tipo:
                return _normalizar_configuracao_regime(configuracao)
    return {}


def _normalizar_configuracao_regime(configuracao: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "periodo": ("periodo", "Periodo"),
        "tipo_dia": ("tipo_dia", "Tipo_Dia"),
        "ano": ("ano", "Ano"),
        "horas": ("horas", "Horas", "Tempo_sim"),
        "curva_carga": ("curva_carga", "Curva_Carga"),
        "escala_carga": ("escala_carga", "Escala_Carga"),
        "dia_semana": ("dia_semana", "Dia_Semana"),
        "tempo_operacao_gerador_h": (
            "tempo_operacao_gerador_h",
            "Tempo_Operacao_Gerador_h",
            "Tempo_Operacao_Gerador",
            "tempo_operacao_h",
            "Tempo_Operacao_h",
        ),
    }
    normalizada: dict[str, Any] = {}
    for destino, chaves in aliases.items():
        for chave in chaves:
            if configuracao.get(chave) is not None:
                normalizada[destino] = configuracao[chave]
                break
    return normalizada


def _primeiro_valor(registro: dict[str, Any], *chaves: str) -> Any:
    """Retorna o primeiro valor preenchido entre aliases de um registro."""

    for chave in chaves:
        if registro.get(chave) is not None:
            return registro[chave]
    return None


def _numero(valor: Any, padrao: float | None) -> float:
    if valor is None or valor == "":
        if padrao is None:
            raise ValueError("Valor numérico obrigatório ausente")
        return float(padrao)
    try:
        return float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor numérico inválido: {valor}") from exc


def _quantidade(valor: Any) -> int:
    valores = valor if isinstance(valor, list) else [valor]
    total = 1
    for item in valores:
        total *= max(int(_numero(item, 1.0)), 1)
    return total


def _janela(valor: Any) -> tuple[int, int]:
    if valor is None or valor == "24h":
        return 0, 24
    texto = str(valor).strip()
    if "-" not in texto:
        raise ValueError(f"Janela horária inválida: {valor}")
    inicio, fim = texto.split("-", 1)
    hora_inicio = int(inicio.strip().split(":")[0])
    hora_fim = int(fim.strip().split(":")[0])
    if not 0 <= hora_inicio <= 23 or not 0 <= hora_fim <= 24:
        raise ValueError(f"Janela horária inválida: {valor}")
    return hora_inicio, hora_fim


def _janela_ativa(hora: int, janela: tuple[int, int]) -> bool:
    inicio, fim = janela
    if inicio == fim:
        return False
    if inicio == 0 and fim == 24:
        return True
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


def _arredondar(valor: Any) -> float | None:
    if valor is None or pd.isna(valor):
        return None
    return round(float(valor), 6)


__all__ = [
    "ConfiguracaoRegimePermanente",
    "ErroPerfilCarga",
    "PerfilCargaHoraria",
    "RegimePermanente",
]

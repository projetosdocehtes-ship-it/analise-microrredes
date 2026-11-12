"""Adaptador de simulação para o componente dinâmico de gerador diesel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from Equipamentos.gerador_diesel import GeradorDiesel, ParametrosGeradorDiesel

from .fluxo_potencia import _importar_pandapower


# Mantém o nome público usado pela primeira versão do módulo.
ConfiguracaoGeradorDiesel = ParametrosGeradorDiesel


@dataclass(frozen=True)
class EventoGeradorDiesel:
    """Evento aplicado ao modelo durante uma janela de tempo."""

    tipo: str
    inicio_s: float
    duracao_s: float | None = None
    carga_kw: float | None = None
    resistencia_falta_ohm: float = 0.0
    reatancia_falta_ohm: float = 0.0

    @property
    def fim_s(self) -> float | None:
        if self.duracao_s is None:
            return None
        return self.inicio_s + self.duracao_s

    def ativo(self, tempo_s: float) -> bool:
        if tempo_s < self.inicio_s:
            return False
        return self.fim_s is None or tempo_s < self.fim_s


@dataclass(frozen=True)
class ConfiguracaoTransitorioDiesel:
    """Configuração do ensaio isolado do gerador."""

    gerador: ConfiguracaoGeradorDiesel = field(default_factory=ConfiguracaoGeradorDiesel)
    passo_s: float = 0.01
    duracao_s: float = 8.0
    carga_inicial_kw: float = 100.0
    fator_potencia_carga: float = 0.95
    modo: str = "offgrid"
    eventos: tuple[EventoGeradorDiesel, ...] = ()
    comprimento_linha_km: float = 0.05
    resistencia_linha_ohm_km: float = 0.642
    reatancia_linha_ohm_km: float = 0.083
    capacitancia_linha_nf_km: float = 0.0
    corrente_linha_max_ka: float = 0.40

    def __post_init__(self) -> None:
        if self.passo_s <= 0 or self.duracao_s <= 0:
            raise ValueError("passo_s e duracao_s devem ser positivos")
        menor_constante = min(
            self.gerador.tempo_governador_s,
            self.gerador.tempo_motor_s,
            self.gerador.tempo_avr_s,
        )
        if self.passo_s > menor_constante / 5.0:
            raise ValueError("passo_s deve ser no máximo 1/5 da menor constante de tempo")
        if self.carga_inicial_kw < 0:
            raise ValueError("carga_inicial_kw não pode ser negativa")
        if not 0 < self.fator_potencia_carga <= 1:
            raise ValueError("fator_potencia_carga deve estar entre zero e um")
        if self.modo not in {"offgrid", "ilhado"}:
            raise ValueError("O primeiro modelo transitório aceita somente modo offgrid")
        if self.comprimento_linha_km < 0 or self.resistencia_linha_ohm_km < 0 or self.reatancia_linha_ohm_km < 0:
            raise ValueError("Os parâmetros da linha não podem ser negativos")
        if self.corrente_linha_max_ka <= 0:
            raise ValueError("corrente_linha_max_ka deve ser positiva")
        for evento in self.eventos:
            if evento.inicio_s < 0:
                raise ValueError("inicio_s do evento não pode ser negativo")
            if evento.duracao_s is not None and evento.duracao_s <= 0:
                raise ValueError("duracao_s do evento deve ser positiva")
            if evento.tipo in {"degrau_carga", "carga"} and (evento.carga_kw is None or evento.carga_kw < 0):
                raise ValueError("evento de carga deve informar carga_kw não negativa")
            if evento.tipo in {"curto_circuito", "curto_circuito_3ph", "curto_3ph"}:
                if evento.duracao_s is None:
                    raise ValueError("curto-circuito deve informar duracao_s")
                if evento.resistencia_falta_ohm < 0 or evento.reatancia_falta_ohm < 0:
                    raise ValueError("impedâncias da falta não podem ser negativas")

    @classmethod
    def from_json(cls, caminho: str | Path) -> "ConfiguracaoTransitorioDiesel":
        arquivo = Path(caminho).expanduser().resolve()
        if not arquivo.is_file():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {arquivo}")
        try:
            documento = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de configuração inválido: {arquivo}") from exc
        if not isinstance(documento, dict):
            raise ValueError("A configuração do gerador deve ser um objeto JSON")
        estudos = documento.get("estudos") or {}
        configuracao_simulacao = (
            estudos.get("transitorio") or estudos.get("transiente")
            if isinstance(estudos, dict)
            else {}
        ) or documento.get("Config_Simulacao") or documento.get("config_simulacao") or {}
        if isinstance(configuracao_simulacao, list):
            configuracao_simulacao = configuracao_simulacao[0] if configuracao_simulacao else {}
        if not isinstance(configuracao_simulacao, dict):
            raise ValueError("Config_Simulacao deve ser um objeto ou uma lista com um objeto")

        dados_gerador = documento.get("gerador_diesel") or documento.get("geradordiesel_info") or {}
        if isinstance(dados_gerador, list):
            dados_gerador = dados_gerador[0] if dados_gerador else {}
        if not isinstance(dados_gerador, dict):
            raise ValueError("gerador_diesel deve ser um objeto ou uma lista com um objeto")
        gerador = ConfiguracaoGeradorDiesel(
            **_filtrar_dataclass(_normalizar_dados_gerador(dados_gerador), ConfiguracaoGeradorDiesel)
        )
        eventos = tuple(
            EventoGeradorDiesel(**_filtrar_dataclass(item, EventoGeradorDiesel))
            for item in documento.get("eventos", [])
            if isinstance(item, dict)
        )
        rede_teste = documento.get("rede_teste") or {}
        if not isinstance(rede_teste, dict):
            raise ValueError("rede_teste deve ser um objeto")
        return cls(
            gerador=gerador,
            passo_s=_primeiro_valor(documento, configuracao_simulacao, "passo_s", "Passo_sim", padrao=0.01),
            duracao_s=_primeiro_valor(documento, configuracao_simulacao, "duracao_s", "Tempo_sim", padrao=8.0),
            carga_inicial_kw=_primeiro_valor(documento, rede_teste, "carga_inicial_kw", padrao=100.0),
            fator_potencia_carga=_primeiro_valor(documento, rede_teste, "fator_potencia_carga", padrao=0.95),
            modo=_primeiro_valor(documento, configuracao_simulacao, "modo", "Modo", padrao="offgrid"),
            eventos=eventos,
            comprimento_linha_km=_primeiro_valor(documento, rede_teste, "comprimento_linha_km", padrao=0.05),
            resistencia_linha_ohm_km=_primeiro_valor(documento, rede_teste, "resistencia_linha_ohm_km", padrao=0.642),
            reatancia_linha_ohm_km=_primeiro_valor(documento, rede_teste, "reatancia_linha_ohm_km", padrao=0.083),
            capacitancia_linha_nf_km=_primeiro_valor(documento, rede_teste, "capacitancia_linha_nf_km", padrao=0.0),
            corrente_linha_max_ka=_primeiro_valor(documento, rede_teste, "corrente_linha_max_ka", padrao=0.40),
        )


class TransitorioGeradorDiesel:
    """Executa o componente de equipamento e a rede de teste pandapower."""

    def __init__(self, configuracao: ConfiguracaoTransitorioDiesel):
        self.configuracao = configuracao

    def montar_rede_pandapower(self, carga_kw: float | None = None) -> tuple[Any, dict[str, int]]:
        """Monta uma rede de teste gerador--linha--PCC--carga."""

        pp = _importar_pandapower()
        cfg = self.configuracao
        gerador = cfg.gerador
        sn_mva = gerador.potencia_nominal_kw / 1000.0 / gerador.fator_potencia
        net = pp.create_empty_network(sn_mva=max(sn_mva, 0.1))
        barra_gerador = pp.create_bus(net, vn_kv=gerador.tensao_nominal_kv, name="Barra_Gerador_Diesel")
        barra_pcc = pp.create_bus(net, vn_kv=gerador.tensao_nominal_kv, name="PCC_Diesel")
        pp.create_line_from_parameters(
            net,
            from_bus=barra_gerador,
            to_bus=barra_pcc,
            length_km=max(cfg.comprimento_linha_km, 1e-6),
            r_ohm_per_km=cfg.resistencia_linha_ohm_km,
            x_ohm_per_km=cfg.reatancia_linha_ohm_km,
            c_nf_per_km=cfg.capacitancia_linha_nf_km,
            max_i_ka=cfg.corrente_linha_max_ka,
            name="Linha do gerador ao PCC",
        )
        carga = cfg.carga_inicial_kw if carga_kw is None else carga_kw
        pp.create_load(
            net,
            barra_pcc,
            p_mw=carga / 1000.0,
            q_mvar=_potencia_reativa_mvar(carga, cfg.fator_potencia_carga),
            name="Carga de teste",
        )
        potencia_inicial = gerador.potencia_inicial_kw
        if potencia_inicial is None:
            potencia_inicial = _limitar(
                carga,
                gerador.potencia_minima_kw,
                gerador.potencia_maxima_kw or gerador.potencia_nominal_kw,
            )
        indice_gen = pp.create_gen(
            net,
            barra_gerador,
            p_mw=potencia_inicial / 1000.0,
            vm_pu=gerador.tensao_referencia_pu,
            sn_mva=sn_mva,
            name=gerador.id_gerador,
            max_p_mw=(gerador.potencia_maxima_kw or gerador.potencia_nominal_kw) / 1000.0,
            min_p_mw=gerador.potencia_minima_kw / 1000.0,
            type="sync",
            slack=True,
            vn_kv=gerador.tensao_nominal_kv,
            xdss_pu=gerador.xdss_pu,
            rdss_ohm=gerador.rdss_ohm,
            cos_phi=gerador.fator_potencia,
        )
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=True, numba=False)
        return net, {"barra_gerador": barra_gerador, "barra_pcc": barra_pcc, "indice_gen": indice_gen}

    def calcular_curto_circuito(self, carga_kw: float | None = None) -> dict[str, Any]:
        """Calcula a corrente inicial trifásica no PCC com pandapower."""

        from pandapower.shortcircuit import calc_sc

        net, indices = self.montar_rede_pandapower(carga_kw=carga_kw)
        calc_sc(net, bus=indices["barra_pcc"], fault="3ph", case="max", ip=False, ith=False)
        resultado = net.res_bus_sc.loc[indices["barra_pcc"]]
        return {
            "motor": "pandapower.shortcircuit.calc_sc",
            "fault": "3ph",
            "barra": net.bus.at[indices["barra_pcc"], "name"],
            "ikss_ka": float(resultado["ikss_ka"]),
            "ip_ka": None,
            "ith_ka": None,
            "skss_mva": float(resultado["skss_mw"]),
            "parametros_fonte": {
                "sn_mva": float(net.gen.at[indices["indice_gen"], "sn_mva"]),
                "vn_kv": self.configuracao.gerador.tensao_nominal_kv,
                "xdss_pu": self.configuracao.gerador.xdss_pu,
                "rdss_ohm": self.configuracao.gerador.rdss_ohm,
            },
        }

    def executar(self) -> dict[str, Any]:
        cfg = self.configuracao
        gerador = cfg.gerador
        numero_passos = int(round(cfg.duracao_s / cfg.passo_s)) + 1
        tempo = np.arange(numero_passos, dtype=float) * cfg.passo_s
        curto_rede = self.calcular_curto_circuito(carga_kw=cfg.carga_inicial_kw)
        modelo = GeradorDiesel(gerador)
        modelo.inicializar(cfg.carga_inicial_kw)
        potencia_referencia = modelo.estado.potencia_mecanica_kw
        evento_curto_anterior: EventoGeradorDiesel | None = None
        serie: list[dict[str, Any]] = []

        for instante in tempo:
            instante = float(instante)
            carga_kw, evento_carga = self._carga_no_instante(instante)
            evento_curto = self._curto_no_instante(instante)
            q_carga_mvar = _potencia_reativa_mvar(carga_kw, cfg.fator_potencia_carga)
            falha_ativa = evento_curto is not None
            tensao_atual_pu = modelo.estado.tensao_pu
            if falha_ativa:
                tensao_alvo_pu = 0.12
                potencia_eletrica_kw = carga_kw * tensao_atual_pu**2
                inicio_curto = instante if evento_curto is not evento_curto_anterior else float(evento_curto.inicio_s)
                corrente_curto_ka = modelo.corrente_curto_transitoria(
                    curto_rede["ikss_ka"],
                    instante - inicio_curto,
                    resistencia_falta_ohm=evento_curto.resistencia_falta_ohm,
                    reatancia_falta_ohm=evento_curto.reatancia_falta_ohm,
                    comprimento_linha_km=cfg.comprimento_linha_km,
                    resistencia_linha_ohm_km=cfg.resistencia_linha_ohm_km,
                    reatancia_linha_ohm_km=cfg.reatancia_linha_ohm_km,
                )
            else:
                queda_carga = gerador.queda_tensao_carga_pu * q_carga_mvar / max(gerador.potencia_nominal_kw / 1000.0, 1e-9)
                tensao_alvo_pu = _limitar(
                    gerador.tensao_referencia_pu - queda_carga,
                    gerador.tensao_minima_pu,
                    gerador.tensao_maxima_pu,
                )
                potencia_eletrica_kw = carga_kw * tensao_atual_pu**2
                corrente_curto_ka = 0.0

            corrente_carga_ka = _corrente_trifasica_ka(
                math.hypot(carga_kw / 1000.0, q_carga_mvar),
                gerador.tensao_nominal_kv * max(tensao_atual_pu, 0.05),
            )
            potencia_comando = modelo.comando_governador(potencia_referencia)
            erro_tensao = gerador.tensao_referencia_pu - tensao_atual_pu
            tensao_comando_pu = (
                tensao_alvo_pu
                if falha_ativa
                else _limitar(
                    tensao_alvo_pu + gerador.ganho_avr * erro_tensao * cfg.passo_s / gerador.tempo_avr_s,
                    gerador.tensao_minima_pu,
                    gerador.tensao_maxima_pu,
                )
            )
            estado = modelo.estado
            serie.append(
                {
                    "tempo_s": round(instante, 9),
                    "carga_kw": round(carga_kw, 6),
                    "evento_carga": evento_carga.tipo if evento_carga else None,
                    "curto_circuito_ativo": falha_ativa,
                    "frequencia_hz": round(estado.frequencia_hz, 6),
                    "velocidade_pu": round(estado.frequencia_hz / gerador.frequencia_nominal_hz, 6),
                    "angulo_rotor_rad": round(estado.angulo_rotor_rad, 6),
                    "potencia_comando_governador_kw": round(potencia_comando, 6),
                    "potencia_governador_kw": round(estado.potencia_governador_kw, 6),
                    "potencia_mecanica_kw": round(estado.potencia_mecanica_kw, 6),
                    "potencia_eletrica_kw": round(potencia_eletrica_kw, 6),
                    "balanco_acelerante_kw": round(estado.potencia_mecanica_kw - potencia_eletrica_kw, 6),
                    "tensao_pu": round(estado.tensao_pu, 6),
                    "tensao_alvo_pu": round(tensao_alvo_pu, 6),
                    "corrente_carga_ka": round(corrente_carga_ka, 6),
                    "corrente_curto_ka": round(corrente_curto_ka, 6),
                    "corrente_pcc_ka": round(max(corrente_carga_ka, corrente_curto_ka), 6),
                }
            )
            modelo.passo(cfg.passo_s, potencia_eletrica_kw, tensao_comando_pu, potencia_referencia)
            evento_curto_anterior = evento_curto

        return {
            "tipo_analise": "transitorio_gerador_diesel_reduzido",
            "modelo": "componente_Equipamentos_GeradorDiesel",
            "modo": cfg.modo,
            "configuracao": {
                "simulacao": _jsonable(asdict(cfg)),
                "gerador": _jsonable(asdict(gerador)),
            },
            "pandapower": {
                "versao": _versao_pandapower(),
                "elemento": "gen",
                "curto_circuito_inicial": curto_rede,
            },
            "premissas": {
                "passo_fixo_s": cfg.passo_s,
                "equacoes_diferenciais": "Equipamentos.GeradorDiesel.equacoes_diferenciais",
                "curto_circuito": "ikss inicial do pandapower com decaimento subtransitório reduzido",
                "limites": "potência mecânica limitada entre mínima e máxima; tensão limitada pelos limites configurados",
            },
            "resumo": _resumo(serie, gerador),
            "serie_temporal": serie,
        }

    def _carga_no_instante(self, instante: float) -> tuple[float, EventoGeradorDiesel | None]:
        carga = self.configuracao.carga_inicial_kw
        evento_ativo: EventoGeradorDiesel | None = None
        for evento in self.configuracao.eventos:
            if evento.tipo not in {"degrau_carga", "carga"} or not evento.ativo(instante):
                continue
            carga = float(evento.carga_kw or 0.0)
            evento_ativo = evento
        return carga, evento_ativo

    def _curto_no_instante(self, instante: float) -> EventoGeradorDiesel | None:
        eventos = [
            evento
            for evento in self.configuracao.eventos
            if evento.tipo in {"curto_circuito", "curto_circuito_3ph", "curto_3ph"} and evento.ativo(instante)
        ]
        return eventos[-1] if eventos else None


def _filtrar_dataclass(dados: dict[str, Any], classe: type[Any]) -> dict[str, Any]:
    campos = {campo.name for campo in fields(classe)}
    return {chave: valor for chave, valor in dados.items() if chave in campos}


def _primeiro_valor(
    principal: dict[str, Any],
    secundario: dict[str, Any],
    *chaves: str,
    padrao: Any,
) -> Any:
    for chave in chaves:
        if chave in principal and principal[chave] is not None:
            return principal[chave]
        if chave in secundario and secundario[chave] is not None:
            return secundario[chave]
    return padrao


def _normalizar_dados_gerador(dados: dict[str, Any]) -> dict[str, Any]:
    """Aceita o bloco novo e os nomes essenciais do contrato legado."""

    normalizado = dict(dados)
    aliases = {
        "id_gerador": "diesel_id",
        "potencia_nominal_kw": "potencia_nominal",
        "frequencia_nominal_hz": "frequencia",
        "fator_potencia": "fp",
    }
    for destino, origem in aliases.items():
        if destino not in normalizado and origem in dados:
            normalizado[destino] = dados[origem]
    if "tensao_nominal_kv" not in normalizado and "tensao_nominal" in dados:
        normalizado["tensao_nominal_kv"] = float(dados["tensao_nominal"]) / 1000.0
    return normalizado


def _potencia_reativa_mvar(potencia_kw: float, fator_potencia: float) -> float:
    return potencia_kw * math.tan(math.acos(fator_potencia)) / 1000.0


def _corrente_trifasica_ka(potencia_mva: float, tensao_kv: float) -> float:
    if tensao_kv <= 0:
        return 0.0
    return potencia_mva / (math.sqrt(3.0) * tensao_kv)


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return min(max(float(valor), float(minimo)), float(maximo))


def _versao_pandapower() -> str:
    pp = _importar_pandapower()
    return str(getattr(pp, "__version__", "desconhecida"))


def _resumo(serie: list[dict[str, Any]], gerador: ConfiguracaoGeradorDiesel) -> dict[str, Any]:
    frequencias = [item["frequencia_hz"] for item in serie]
    tensoes = [item["tensao_pu"] for item in serie]
    correntes_curto = [item["corrente_curto_ka"] for item in serie]
    return {
        "passos": len(serie),
        "duracao_s": serie[-1]["tempo_s"] if serie else 0.0,
        "frequencia_min_hz": min(frequencias, default=None),
        "frequencia_max_hz": max(frequencias, default=None),
        "desvio_frequencia_max_hz": max((abs(valor - gerador.frequencia_nominal_hz) for valor in frequencias), default=0.0),
        "tensao_min_pu": min(tensoes, default=None),
        "tensao_max_pu": max(tensoes, default=None),
        "corrente_curto_max_ka": max(correntes_curto, default=0.0),
        "horas_equivalentes_falta": sum(1 for item in serie if item["curto_circuito_ativo"]) / 3600.0,
        "passos_com_degrau_carga": sum(1 for item in serie if item["evento_carga"] is not None),
    }


def _jsonable(valor: Any) -> Any:
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, dict):
        return {chave: _jsonable(item) for chave, item in valor.items()}
    if isinstance(valor, (tuple, list)):
        return [_jsonable(item) for item in valor]
    return valor


__all__ = [
    "ConfiguracaoGeradorDiesel",
    "ConfiguracaoTransitorioDiesel",
    "EventoGeradorDiesel",
    "TransitorioGeradorDiesel",
]

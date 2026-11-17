"""Ensaio transitório isolado do equivalente elétrico PEM."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path
from typing import Any

from Equipamentos.eletrolisador_pem import EletrolisadorPEM, ParametrosEletrolisadorPEM


@dataclass(frozen=True)
class EventoCorrenteEletrolisadorPEM:
    """Intervalo em que uma corrente externa é aplicada ao stack."""

    tipo: str
    inicio_s: float
    corrente_stack_A: float
    duracao_s: float | None = None

    def __post_init__(self) -> None:
        if self.tipo not in {"degrau_corrente", "corrente"}:
            raise ValueError("tipo de evento deve ser degrau_corrente ou corrente")
        if not _finito(self.inicio_s) or self.inicio_s < 0:
            raise ValueError("inicio_s deve ser não negativo e finito")
        if not _finito(self.corrente_stack_A):
            raise ValueError("corrente_stack_A deve ser finita")
        if self.duracao_s is not None and (not _finito(self.duracao_s) or self.duracao_s <= 0):
            raise ValueError("duracao_s deve ser positiva e finita")

    @property
    def fim_s(self) -> float | None:
        return None if self.duracao_s is None else self.inicio_s + self.duracao_s

    def ativo(self, tempo_s: float) -> bool:
        return tempo_s >= self.inicio_s and (self.fim_s is None or tempo_s < self.fim_s)


@dataclass(frozen=True)
class ConfiguracaoTransitorioEletrolisadorPEM:
    eletrolisador: ParametrosEletrolisadorPEM
    passo_s: float = 0.01
    duracao_s: float = 8.0
    corrente_inicial_A: float = 0.0
    quantidade: int = 1
    estado_inicial: tuple[float, ...] | None = None
    eventos: tuple[EventoCorrenteEletrolisadorPEM, ...] = ()

    def __post_init__(self) -> None:
        if not _finito(self.passo_s) or self.passo_s <= 0:
            raise ValueError("passo_s deve ser positivo e finito")
        if not _finito(self.duracao_s) or self.duracao_s <= 0:
            raise ValueError("duracao_s deve ser positiva e finita")
        if not _finito(self.corrente_inicial_A):
            raise ValueError("corrente_inicial_A deve ser finita")
        if isinstance(self.quantidade, bool) or not isinstance(self.quantidade, int) or self.quantidade < 1:
            raise ValueError("quantidade deve ser um inteiro positivo")
        menor_constante = min(self.eletrolisador.constantes_tempo_s)
        if self.passo_s > menor_constante / 5.0:
            raise ValueError("passo_s deve ser no máximo 1/5 da menor constante de tempo do EEC")

    @classmethod
    def from_json(cls, caminho: str | Path) -> "ConfiguracaoTransitorioEletrolisadorPEM":
        arquivo = Path(caminho).expanduser().resolve()
        if not arquivo.is_file():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {arquivo}")
        try:
            documento = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de configuração inválido: {arquivo}") from exc
        if not isinstance(documento, dict):
            raise ValueError("A configuração do eletrolisador deve ser um objeto JSON")

        dados_eletrolisador = _primeiro_registro(documento, "eletrolisador_pem_info")
        if not dados_eletrolisador:
            dados_eletrolisador = documento.get("eletrolisador_pem") or {}
        if not isinstance(dados_eletrolisador, dict) or not dados_eletrolisador:
            raise ValueError("Informe eletrolisador_pem_info[0] com os parâmetros do stack")
        parametros = _criar_parametros(dados_eletrolisador)

        estudos = documento.get("estudos") or {}
        configuracao = {}
        if isinstance(estudos, dict):
            configuracao = (
                estudos.get("transitorio_eletrolisador_pem")
                or estudos.get("transitorio")
                or {}
            )
        if not configuracao:
            configuracao = documento.get("Config_Simulacao") or documento.get("config_simulacao") or {}
        if isinstance(configuracao, list):
            configuracao = configuracao[0] if configuracao else {}
        if not isinstance(configuracao, dict):
            raise ValueError("Config_Simulacao deve ser um objeto ou uma lista com um objeto")

        dados_eventos = documento.get("eventos", [])
        if not isinstance(dados_eventos, list):
            raise ValueError("eventos deve ser uma lista")
        if any(not isinstance(item, dict) for item in dados_eventos):
            raise ValueError("cada evento deve ser um objeto")
        eventos = tuple(
            _criar_evento(item)
            for item in dados_eventos
        )
        estado = configuracao.get("estado_inicial")
        if estado is not None:
            if not isinstance(estado, list):
                raise ValueError("estado_inicial deve ser uma lista de tensões por célula")
            estado = tuple(float(valor) for valor in estado)

        return cls(
            eletrolisador=parametros,
            passo_s=_numero(
                _primeiro_valor(configuracao, "passo_s", "Passo_sim", padrao=0.01),
                "passo_s",
            ),
            duracao_s=_numero(
                _primeiro_valor(configuracao, "duracao_s", "Tempo_sim", padrao=8.0),
                "duracao_s",
            ),
            corrente_inicial_A=_numero(
                _primeiro_valor(
                    configuracao,
                    "corrente_inicial_A",
                    "corrente_stack_A",
                    padrao=_primeiro_valor(
                        dados_eletrolisador,
                        "corrente_stack_A",
                        "i_stack_A",
                        padrao=0.0,
                    ),
                ),
                "corrente_inicial_A",
            ),
            quantidade=_quantidade(dados_eletrolisador.get("quantidade", 1)),
            estado_inicial=estado,
            eventos=eventos,
        )


class TransitorioEletrolisadorPEM:
    """Aplica corrente prescrita e registra a resposta do EEC em CC."""

    def __init__(self, configuracao: ConfiguracaoTransitorioEletrolisadorPEM):
        self.configuracao = configuracao

    def executar(self) -> dict[str, Any]:
        cfg = self.configuracao
        tempo = self._linha_do_tempo()
        modelo = EletrolisadorPEM(cfg.eletrolisador)
        modelo.inicializar(cfg.corrente_inicial_A, cfg.estado_inicial)
        serie: list[dict[str, Any]] = []

        for indice, instante in enumerate(tempo):
            corrente, evento = self._corrente_no_instante(instante)
            saida = modelo.calcular_saida(corrente)
            serie.append(
                {
                    "tempo_s": round(instante, 9),
                    "corrente_stack_A": round(corrente, 9),
                    "evento_corrente": evento.tipo if evento else None,
                    "tensao_polarizacao_celula_V": round(saida["polarization_voltage_cell_V"], 9),
                    "tensao_celula_V": round(saida["cell_voltage_V"], 9),
                    "tensao_stack_V": round(saida["stack_voltage_V"], 9),
                    "potencia_stack_W": round(saida["stack_power_W"], 9),
                    "potencia_total_stacks_W": round(saida["stack_power_W"] * cfg.quantidade, 9),
                    "estado_V_dle_celula_V": round(modelo.estado.V_dle_cell_V, 9),
                    "estado_V_act_celula_V": round(modelo.estado.V_act_cell_V, 9),
                    "estado_V_con_celula_V": round(modelo.estado.V_con_cell_V, 9),
                }
            )
            if indice + 1 < len(tempo):
                modelo.passo(tempo[indice + 1] - instante, corrente)

        return {
            "tipo_analise": "transitorio_eletrolisador_pem",
            "modelo": "Equipamentos.EletrolisadorPEM",
            "fronteira": "stack_cc_de_uma_porta",
            "configuracao": {
                "simulacao": _jsonable(asdict(cfg)),
                "eletrolisador": _jsonable(asdict(cfg.eletrolisador)),
            },
            "premissas": {
                "entrada": "corrente do stack prescrita pelo circuito ou controlador externo",
                "integracao": "Euler explícito com passo limitado a 1/5 da menor constante de tempo",
                "potencia": "V_stack * I_stack; positiva representa potência absorvida",
                "processos_fora_do_modelo": [
                    "produção de hidrogênio e oxigênio",
                    "eficiência faradaica",
                    "temperatura e pressão",
                    "conversor CC/CA",
                ],
            },
            "ponto_operacao_estacionario_inicial": modelo.ponto_operacao_estacionario(
                cfg.corrente_inicial_A
            ),
            "resumo": _resumo(serie),
            "serie_temporal": serie,
        }

    def _linha_do_tempo(self) -> list[float]:
        """Inclui amostras regulares, bordas dos eventos e o fim exato do estudo."""

        cfg = self.configuracao
        quantidade_passos = int(math.floor(cfg.duracao_s / cfg.passo_s))
        pontos = {
            round(indice * cfg.passo_s, 12)
            for indice in range(quantidade_passos + 1)
            if indice * cfg.passo_s < cfg.duracao_s
        }
        pontos.add(cfg.duracao_s)
        for evento in cfg.eventos:
            if 0 <= evento.inicio_s <= cfg.duracao_s:
                pontos.add(evento.inicio_s)
            fim = evento.fim_s
            if fim is not None and 0 <= fim <= cfg.duracao_s:
                pontos.add(fim)
        return sorted(pontos)

    def _corrente_no_instante(
        self, instante: float
    ) -> tuple[float, EventoCorrenteEletrolisadorPEM | None]:
        corrente = self.configuracao.corrente_inicial_A
        evento_ativo: EventoCorrenteEletrolisadorPEM | None = None
        for evento in self.configuracao.eventos:
            if evento.ativo(instante):
                corrente = evento.corrente_stack_A
                evento_ativo = evento
        return corrente, evento_ativo


def _criar_parametros(dados: dict[str, Any]) -> ParametrosEletrolisadorPEM:
    campos = {campo.name for campo in fields(ParametrosEletrolisadorPEM)}
    parametros = {chave: valor for chave, valor in dados.items() if chave in campos}
    if "id_eletrolisador" not in parametros and dados.get("eletrolisador_id"):
        parametros["id_eletrolisador"] = dados["eletrolisador_id"]
    obrigatorios = (
        "V_rev_cell_V",
        "R_ohm_cell_Ohm",
        "R_act_cell_Ohm",
        "R_con_cell_Ohm",
        "n_series_cells",
    )
    faltantes = [nome for nome in obrigatorios if nome not in parametros]
    if faltantes:
        raise ValueError(f"Parâmetros obrigatórios do eletrolisador ausentes: {', '.join(faltantes)}")
    for nome in (
        "V_rev_cell_V",
        "R_ohm_cell_Ohm",
        "R_act_cell_Ohm",
        "R_con_cell_Ohm",
        "C_dle_cell_F",
        "C_act_cell_F",
        "C_con_cell_F",
    ):
        if parametros.get(nome) is not None:
            parametros[nome] = _numero(parametros[nome], nome)
    parametros["n_series_cells"] = _inteiro(parametros["n_series_cells"], "n_series_cells")
    parametros["n_parallel_strings"] = _inteiro(
        parametros.get("n_parallel_strings", 1), "n_parallel_strings"
    )
    try:
        return ParametrosEletrolisadorPEM(**parametros)
    except TypeError as exc:
        raise ValueError(f"Parâmetros do eletrolisador inválidos: {exc}") from exc


def _primeiro_registro(documento: dict[str, Any], chave: str) -> dict[str, Any]:
    registros = documento.get(chave) or []
    if not isinstance(registros, list):
        raise ValueError(f"{chave} deve ser uma lista de registros")
    if not registros:
        return {}
    if not isinstance(registros[0], dict):
        raise ValueError(f"{chave}[0] deve ser um objeto")
    return registros[0]


def _criar_evento(dados: dict[str, Any]) -> EventoCorrenteEletrolisadorPEM:
    if "inicio_s" not in dados or "corrente_stack_A" not in dados:
        raise ValueError("cada evento requer inicio_s e corrente_stack_A")
    duracao = dados.get("duracao_s")
    return EventoCorrenteEletrolisadorPEM(
        tipo=str(dados.get("tipo", "degrau_corrente")),
        inicio_s=_numero(dados["inicio_s"], "inicio_s"),
        corrente_stack_A=_numero(dados["corrente_stack_A"], "corrente_stack_A"),
        duracao_s=_numero(duracao, "duracao_s") if duracao is not None else None,
    )


def _primeiro_valor(principal: dict[str, Any], *chaves: str, padrao: Any) -> Any:
    for chave in chaves:
        if principal.get(chave) is not None:
            return principal[chave]
    return padrao


def _inteiro(valor: Any, nome: str) -> int:
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nome} deve ser um inteiro positivo") from exc
    if not math.isfinite(numero) or numero < 1 or not numero.is_integer():
        raise ValueError(f"{nome} deve ser um inteiro positivo")
    return int(numero)


def _quantidade(valor: Any) -> int:
    valores = valor if isinstance(valor, list) else [valor]
    total = 1
    for item in valores:
        total *= _inteiro(item, "quantidade")
    return total


def _numero(valor: Any, nome: str) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nome} deve ser numérico") from exc
    if not math.isfinite(numero):
        raise ValueError(f"{nome} deve ser finito")
    return numero


def _finito(valor: Any) -> bool:
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError, OverflowError):
        return False


def _jsonable(valor: Any) -> Any:
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, dict):
        return {chave: _jsonable(item) for chave, item in valor.items()}
    if isinstance(valor, (tuple, list)):
        return [_jsonable(item) for item in valor]
    return valor


def _resumo(serie: list[dict[str, Any]]) -> dict[str, Any]:
    tensoes = [item["tensao_stack_V"] for item in serie]
    potencias = [item["potencia_total_stacks_W"] for item in serie]
    return {
        "passos": len(serie),
        "duracao_s": serie[-1]["tempo_s"] if serie else 0.0,
        "tensao_stack_min_V": min(tensoes, default=None),
        "tensao_stack_max_V": max(tensoes, default=None),
        "potencia_total_max_W": max(potencias, default=None),
        "passos_com_evento_corrente": sum(1 for item in serie if item["evento_corrente"] is not None),
    }


__all__ = [
    "ConfiguracaoTransitorioEletrolisadorPEM",
    "EventoCorrenteEletrolisadorPEM",
    "TransitorioEletrolisadorPEM",
]

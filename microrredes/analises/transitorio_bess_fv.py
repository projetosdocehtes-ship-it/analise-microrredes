"""Simulação transitória reduzida de um sistema on-grid FV+BESS+carga.

O modelo é propositalmente pequeno: representa a energização do barramento,
o acoplamento de potência ativa com a rede e uma perda temporária de strings
do FV. Ele é adequado para validar o cenário e produzir curvas em segundos;
não substitui um EMT trifásico detalhado do inversor.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from Equipamentos.bess import BESS, ParametrosBESS
from Equipamentos.gerador_diesel import GeradorDiesel

from .falhas import AnaliseFalhas
from .fluxo_potencia import AnaliseFluxoPotencia
from .transitorio_gerador_diesel import ConfiguracaoTransitorioDiesel, EventoGeradorDiesel, TransitorioGeradorDiesel


@dataclass(frozen=True)
class ConfiguracaoTransitorio:
    entrada: str | Path
    consumo_diario_kwh: float = 650.0
    pv_kwp: float = 80.0
    bess_kwh: float = 100.0
    bess_kw: float = 40.0
    strings_fv: int = 16
    strings_perdidas: int = 4
    forcar_on_grid: bool = False
    falhas: str | Path | None = None
    saida: str | Path | None = None
    graficos_dir: str | Path | None = None


class TransitorioBessFV:
    """Executa o cenário temporal definido em ``Entradas.Json``."""

    def __init__(self, configuracao: ConfiguracaoTransitorio):
        self.configuracao = configuracao

    def executar(self) -> dict[str, Any]:
        cfg = self.configuracao
        entrada = Path(cfg.entrada).expanduser().resolve()
        documento = json.loads(entrada.read_text(encoding="utf-8"))
        if self._possui_diesel(documento):
            return self._executar_integrado_diesel(entrada, documento)
        sim = (documento.get("Config_Simulacao") or [{}])[0]

        passo = float(sim.get("Passo_sim", 2e-5))
        duracao = float(sim.get("Tempo_sim", 1.0))
        if passo <= 0 or duracao <= 0:
            raise ValueError("Passo_sim e Tempo_sim devem ser positivos.")

        numero_passos = int(round(duracao / passo))
        if numero_passos < 2:
            raise ValueError("A configuração transiente precisa de pelo menos dois passos.")

        falha, avisos = self._carregar_falha(documento, entrada)
        inicio_falha = float(falha["inicio_s"])
        fim_falha = inicio_falha + float(falha["duracao_s"])
        strings_totais = int(falha.get("strings_totais", cfg.strings_fv))
        strings_perdidas = int(falha.get("strings_perdidas", cfg.strings_perdidas))
        if strings_totais <= 0 or not 0 <= strings_perdidas <= strings_totais:
            raise ValueError("A contingência deve ter strings_perdidas entre zero e strings_totais.")

        on_grid_original = bool(documento.get("conectado_rede", False))
        on_grid = on_grid_original or cfg.forcar_on_grid
        if cfg.forcar_on_grid and not on_grid_original:
            avisos.append("conectado_rede estava false; o cenário foi executado on-grid por solicitação do usuário.")

        tempo = np.arange(numero_passos, dtype=float) * passo
        falha_ativa = (tempo >= inicio_falha) & (tempo < fim_falha)

        carga_kw = float(cfg.consumo_diario_kwh) / 24.0
        pv_nominal_kw = float(cfg.pv_kwp)
        perda_fracao = strings_perdidas / strings_totais
        pv_alvo_kw = np.full(numero_passos, pv_nominal_kw, dtype=float)
        pv_alvo_kw[falha_ativa] *= 1.0 - perda_fracao

        # Energização suave do conjunto FV, da carga e dos conversores.
        pv_kw = self._primeira_ordem(pv_alvo_kw, tempo, tau_s=0.04)
        carga_alvo_kw = np.full(numero_passos, carga_kw, dtype=float)
        carga_kw_t = self._primeira_ordem(carga_alvo_kw, tempo, tau_s=0.08)

        p_bess_cmd_kw = np.clip(carga_kw_t - pv_kw, -cfg.bess_kw, cfg.bess_kw)
        p_bess_kw = self._primeira_ordem(p_bess_cmd_kw, tempo, tau_s=0.015)
        soc = np.empty(numero_passos, dtype=float)
        soc[0] = 0.80
        for i in range(1, numero_passos):
            soc[i] = np.clip(
                soc[i - 1] - p_bess_kw[i] * passo / (3600.0 * cfg.bess_kwh),
                0.10,
                0.90,
            )

        p_grid_alvo_kw = carga_kw_t - pv_kw - p_bess_kw if on_grid else np.zeros(numero_passos)
        p_grid_kw = self._primeira_ordem(p_grid_alvo_kw, tempo, tau_s=0.02)
        p_rede_residual_kw = carga_kw_t - pv_kw - p_bess_kw - p_grid_kw

        # Queda de tensão equivalente no PCC por potência importada/exportada.
        # O coeficiente é um equivalente de rede para este estudo reduzido.
        tensao_alvo_pu = np.clip(1.0 - 0.00015 * p_grid_kw, 0.94, 1.06)
        tensao_pcc_pu = self._primeira_ordem(tensao_alvo_pu, tempo, tau_s=0.02, inicial=1.0)
        corrente_pcc_a = np.abs(p_grid_kw) * 1000.0 / (np.sqrt(3.0) * 380.0)

        resultado: dict[str, Any] = {
            "tipo_analise": "transitorio_reduzido_on_grid",
            "modelo": "balanco_de_potencia_com_dinamica_de_primeira_ordem",
            "arquivo_entrada": str(entrada),
            "parametros": {
                "passo_s": passo,
                "duracao_s": duracao,
                "numero_passos": numero_passos,
                "consumo_diario_kwh": cfg.consumo_diario_kwh,
                "carga_media_kw": carga_kw,
                "pv_kwp": pv_nominal_kw,
                "bess_kwh": cfg.bess_kwh,
                "bess_kw": cfg.bess_kw,
                "conectado_rede_entrada": on_grid_original,
                "conectado_rede_simulacao": on_grid,
            },
            "contingencia": {
                "tipo": falha["tipo"],
                "id_pv": falha.get("id_pv"),
                "inicio_s": inicio_falha,
                "fim_s": fim_falha,
                "duracao_s": float(falha["duracao_s"]),
                "strings_totais": strings_totais,
                "strings_perdidas": strings_perdidas,
                "perda_fracao": perda_fracao,
            },
            "avisos": avisos,
            "resumo": {
                "pv_nominal_kwh_equivalente": float(self._integrar(pv_kw, tempo) / 3600.0),
                "pv_perdida_durante_falha_kwh": float(
                    self._integrar((pv_nominal_kw - pv_alvo_kw) * falha_ativa, tempo) / 3600.0
                ),
                "energia_importada_rede_kwh": float(self._integrar(np.maximum(p_grid_kw, 0), tempo) / 3600.0),
                "energia_exportada_rede_kwh": float(self._integrar(np.maximum(-p_grid_kw, 0), tempo) / 3600.0),
                "pcc_tensao_min_pu": float(np.min(tensao_pcc_pu)),
                "pcc_tensao_max_pu": float(np.max(tensao_pcc_pu)),
                "corrente_pcc_max_a": float(np.max(corrente_pcc_a)),
                "soc_inicial": float(soc[0]),
                "soc_final": float(soc[-1]),
                "residual_potencia_max_kw": float(np.max(np.abs(p_rede_residual_kw))),
            },
            "serie_temporal": {
                "tempo_s": tempo.tolist(),
                "falha_ativa": falha_ativa.astype(int).tolist(),
                "pv_kw": pv_kw.tolist(),
                "carga_kw": carga_kw_t.tolist(),
                "bess_kw": p_bess_kw.tolist(),
                "rede_kw": p_grid_kw.tolist(),
                "tensao_pcc_pu": tensao_pcc_pu.tolist(),
                "corrente_pcc_a": corrente_pcc_a.tolist(),
                "soc": soc.tolist(),
            },
        }

        if cfg.graficos_dir:
            resultado["graficos_saida"] = self.gerar_graficos(resultado, cfg.graficos_dir)
        if cfg.saida:
            saida = Path(cfg.saida).expanduser().resolve()
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
            resultado["arquivo_saida"] = str(saida)
        return resultado

    def _executar_integrado_diesel(self, entrada: Path, documento: dict[str, Any]) -> dict[str, Any]:
        """Executa o transitório FV+BESS com o diesel como fonte da microrrede.

        O caminho só é ativado quando o arquivo possui ``geradordiesel_info``.
        Assim os arquivos legados sem diesel continuam usando exatamente o
        balanço reduzido anterior.
        """

        cfg = self.configuracao
        simulacao = _configuracao_simulacao(documento)
        passo = float(simulacao.get("Passo_sim", 0.01))
        duracao = float(simulacao.get("Tempo_sim", 6.0))
        if passo <= 0 or duracao <= 0:
            raise ValueError("Passo_sim e Tempo_sim devem ser positivos.")
        numero_passos = int(round(duracao / passo))
        if numero_passos < 2:
            raise ValueError("A configuração transitória precisa de pelo menos dois passos.")

        config_diesel = ConfiguracaoTransitorioDiesel.from_json(entrada)
        modelo_diesel = GeradorDiesel(config_diesel.gerador)
        carga_inicial_kw = _carga_transitoria(documento, cfg.consumo_diario_kwh / 24.0)
        modelo_diesel.inicializar(carga_inicial_kw)
        eventos = config_diesel.eventos
        rede_teste = documento.get("rede_teste") or {}
        on_grid_original = bool(documento.get("conectado_rede", False))
        on_grid = on_grid_original or cfg.forcar_on_grid

        falha, avisos = self._carregar_falha(documento, entrada)
        inicio_falha = float(falha["inicio_s"])
        fim_falha = inicio_falha + float(falha["duracao_s"])
        strings_totais = int(falha.get("strings_totais", cfg.strings_fv))
        strings_perdidas = int(falha.get("strings_perdidas", cfg.strings_perdidas))
        if strings_totais <= 0 or not 0 <= strings_perdidas <= strings_totais:
            raise ValueError("A contingência deve ter strings_perdidas entre zero e strings_totais.")

        pv_nominal_kw = _pv_nominal(documento, cfg.pv_kwp)
        eficiencia_pv = _numero(_primeiro(documento, "inversor_info").get("Eficiencia"), 1.0)
        pv_nominal_kw *= eficiencia_pv
        tempo = np.arange(numero_passos, dtype=float) * passo
        falha_ativa = (tempo >= inicio_falha) & (tempo < fim_falha)
        pv_alvo_kw = np.full(numero_passos, pv_nominal_kw, dtype=float)
        pv_alvo_kw[falha_ativa] *= 1.0 - strings_perdidas / strings_totais
        pv_kw = self._primeira_ordem(pv_alvo_kw, tempo, tau_s=0.04)

        carga_alvo_kw = np.asarray(
            [_carga_no_instante(float(instante), carga_inicial_kw, eventos) for instante in tempo],
            dtype=float,
        )
        # Nos casos integrados a carga já está conectada em t=0. A resposta
        # de primeira ordem fica reservada para degraus posteriores.
        carga_kw_t = self._primeira_ordem(
            carga_alvo_kw,
            tempo,
            tau_s=0.08,
            inicial=float(carga_alvo_kw[0]),
        )

        bess = _bess_do_documento(documento)
        soc = np.zeros(numero_passos, dtype=float)
        potencia_bess = np.zeros(numero_passos, dtype=float)
        if bess is not None:
            soc[0] = bess.estado.soc

        try:
            curto_inicial = TransitorioGeradorDiesel(config_diesel).calcular_curto_circuito(
                carga_kw=carga_inicial_kw
            )
        except Exception as exc:  # pragma: no cover - depende da instalação elétrica
            curto_inicial = {"erro": str(exc)}

        serie: dict[str, list[Any]] = {
            "tempo_s": tempo.tolist(),
            "falha_ativa": falha_ativa.astype(int).tolist(),
            "gerador_ligado": [],
            "pv_kw": [],
            "carga_kw": [],
            "bess_kw": [],
            "rede_kw": [],
            "diesel_kw": [],
            "deficit_kw": [],
            "curtailment_kw": [],
            "tensao_pcc_pu": [],
            "corrente_pcc_a": [],
            "corrente_curto_ka": [],
            "frequencia_hz": [],
            "potencia_mecanica_diesel_kw": [],
            "soc": [],
        }
        passos_carga = 0
        evento_curto_anterior: EventoGeradorDiesel | None = None
        for indice, instante in enumerate(tempo):
            instante = float(instante)
            carga_kw = float(carga_kw_t[indice])
            pv_atual_kw = float(pv_kw[indice])
            residual_sem_bess_kw = carga_kw - pv_atual_kw
            if bess is None:
                bateria_kw = 0.0
                soc_atual = 0.0
            else:
                comando_bess_kw = _comando_bess(residual_sem_bess_kw, bess)
                estado_bess = bess.passo_potencia(passo, comando_bess_kw)
                bateria_kw = float(estado_bess.potencia_kw)
                soc_atual = float(estado_bess.soc)
            soc[indice] = soc_atual
            potencia_bess[indice] = bateria_kw

            evento_carga = _evento_carga_no_instante(instante, eventos)
            if evento_carga is not None:
                passos_carga += 1
            evento_curto = _evento_curto_no_instante(instante, eventos)
            falha_curto = evento_curto is not None
            residual_kw = carga_kw - pv_atual_kw - bateria_kw
            evento_ligacao = _evento_ligacao_no_instante(instante, eventos)
            diesel_habilitado = (
                (not on_grid)
                or bool(documento.get("operar_diesel_on_grid", False))
                or evento_ligacao is not None
            )
            if diesel_habilitado:
                potencia_alvo_diesel_kw = max(residual_kw, 0.0)
                p_min = config_diesel.gerador.potencia_minima_kw
                p_max = config_diesel.gerador.potencia_maxima_kw or config_diesel.gerador.potencia_nominal_kw
                potencia_diesel_kw = _limitar(max(potencia_alvo_diesel_kw, p_min), p_min, p_max)
            else:
                potencia_alvo_diesel_kw = 0.0
                potencia_diesel_kw = 0.0

            q_carga_mvar = carga_kw * math.tan(math.acos(config_diesel.fator_potencia_carga)) / 1000.0
            tensao_alvo_pu = _limitar(
                config_diesel.gerador.tensao_referencia_pu
                - config_diesel.gerador.queda_tensao_carga_pu
                * q_carga_mvar
                / max(config_diesel.gerador.potencia_nominal_kw / 1000.0, 1e-9),
                config_diesel.gerador.tensao_minima_pu,
                config_diesel.gerador.tensao_maxima_pu,
            )
            corrente_curto_ka = 0.0
            if falha_curto:
                inicio_curto = (
                    float(evento_curto.inicio_s)
                    if evento_curto is not evento_curto_anterior
                    else float(evento_curto.inicio_s)
                )
                ikss = float(curto_inicial.get("ikss_ka", 0.0))
                corrente_curto_ka = modelo_diesel.corrente_curto_transitoria(
                    ikss,
                    instante - inicio_curto,
                    resistencia_falta_ohm=evento_curto.resistencia_falta_ohm,
                    reatancia_falta_ohm=evento_curto.reatancia_falta_ohm,
                    comprimento_linha_km=config_diesel.comprimento_linha_km,
                    resistencia_linha_ohm_km=config_diesel.resistencia_linha_ohm_km,
                    reatancia_linha_ohm_km=config_diesel.reatancia_linha_ohm_km,
                )
                tensao_pcc_pu = 0.12
                potencia_eletrica_diesel_kw = potencia_diesel_kw * tensao_pcc_pu**2
                tensao_comando_pu = tensao_pcc_pu
            else:
                tensao_pcc_pu = modelo_diesel.estado.tensao_pu if diesel_habilitado else _limitar(
                    1.0 - 0.00015 * residual_kw, 0.94, 1.06
                )
                potencia_eletrica_diesel_kw = potencia_diesel_kw
                tensao_comando_pu = tensao_alvo_pu

            if diesel_habilitado:
                modelo_diesel.passo(
                    passo,
                    potencia_eletrica_diesel_kw,
                    tensao_comando_pu,
                    potencia_referencia_kw=max(potencia_alvo_diesel_kw, config_diesel.gerador.potencia_minima_kw),
                )
            rede_kw = residual_kw - potencia_diesel_kw if on_grid else 0.0
            deficit_kw = max(residual_kw - potencia_diesel_kw, 0.0)
            curtailment_kw = max(-residual_kw, 0.0) + max(
                potencia_diesel_kw - max(residual_kw, 0.0), 0.0
            ) if not on_grid else max(-residual_kw, 0.0)
            potencia_pcc_mva = math.hypot((carga_kw - pv_atual_kw - bateria_kw - potencia_diesel_kw) / 1000.0, q_carga_mvar)
            corrente_pcc_a = abs(potencia_pcc_mva) * 1000.0 / (math.sqrt(3.0) * 0.38)

            serie["pv_kw"].append(round(pv_atual_kw, 6))
            serie["gerador_ligado"].append(int(diesel_habilitado))
            serie["carga_kw"].append(round(carga_kw, 6))
            serie["bess_kw"].append(round(bateria_kw, 6))
            serie["rede_kw"].append(round(rede_kw, 6))
            serie["diesel_kw"].append(round(potencia_diesel_kw, 6))
            serie["deficit_kw"].append(round(deficit_kw, 6))
            serie["curtailment_kw"].append(round(curtailment_kw, 6))
            serie["tensao_pcc_pu"].append(round(tensao_pcc_pu, 6))
            serie["corrente_pcc_a"].append(round(max(corrente_pcc_a, corrente_curto_ka * 1000.0), 6))
            serie["corrente_curto_ka"].append(round(corrente_curto_ka, 6))
            serie["frequencia_hz"].append(round(modelo_diesel.estado.frequencia_hz if diesel_habilitado else 60.0, 6))
            serie["potencia_mecanica_diesel_kw"].append(round(modelo_diesel.estado.potencia_mecanica_kw if diesel_habilitado else 0.0, 6))
            serie["soc"].append(round(soc_atual, 6))
            evento_curto_anterior = evento_curto

        rede_pandapower: dict[str, Any] = {}
        try:
            net, _ = AnaliseFluxoPotencia.criar_rede_entrada(entrada)
            rede_pandapower["fluxo_inicial"] = AnaliseFluxoPotencia().executar(net)
            rede_pandapower["curto_circuito_rede"] = AnaliseFalhas().executar(net, tipo="3ph", caso="max")
        except Exception as exc:  # pragma: no cover - depende da rede opcional
            rede_pandapower["erro"] = str(exc)

        resultado: dict[str, Any] = {
            "tipo_analise": "transitorio_reduzido_microrrede_com_diesel",
            "modelo": "PV+BESS+GeradorDiesel",
            "arquivo_entrada": str(entrada),
            "parametros": {
                "passo_s": passo,
                "duracao_s": duracao,
                "numero_passos": numero_passos,
                "pv_kwp": pv_nominal_kw,
                "bess_configurado": bess is not None,
                "conectado_rede_entrada": on_grid_original,
                "conectado_rede_simulacao": on_grid,
                "gerador_diesel": config_diesel.gerador.id_gerador,
            },
            "contingencia": {
                "tipo": falha["tipo"],
                "id_pv": falha.get("id_pv"),
                "inicio_s": inicio_falha,
                "fim_s": fim_falha,
                "duracao_s": float(falha["duracao_s"]),
                "strings_totais": strings_totais,
                "strings_perdidas": strings_perdidas,
                "perda_fracao": strings_perdidas / strings_totais,
            },
            "eventos_diesel": [event.__dict__ for event in eventos],
            "tempo_ligacao_gerador_s": _tempo_primeira_ligacao(eventos),
            "avisos": avisos,
            "pandapower": {
                "rede_entrada": rede_pandapower,
                "curto_circuito_inicial_do_ensaio": curto_inicial,
            },
            "resumo": {
                "passos": numero_passos,
                "passos_com_degrau_carga": passos_carga,
                "energia_carga_kwh": self._integrar(np.asarray(serie["carga_kw"]), tempo) / 3600.0,
                "energia_pv_kwh": self._integrar(np.asarray(serie["pv_kw"]), tempo) / 3600.0,
                "energia_diesel_kwh": self._integrar(np.asarray(serie["diesel_kw"]), tempo) / 3600.0,
                "energia_importada_rede_kwh": self._integrar(np.maximum(np.asarray(serie["rede_kw"]), 0.0), tempo) / 3600.0,
                "energia_deficit_kwh": self._integrar(np.asarray(serie["deficit_kw"]), tempo) / 3600.0,
                "energia_curtailment_kwh": self._integrar(np.asarray(serie["curtailment_kw"]), tempo) / 3600.0,
                "pcc_tensao_min_pu": min(serie["tensao_pcc_pu"]),
                "pcc_tensao_max_pu": max(serie["tensao_pcc_pu"]),
                "corrente_pcc_max_a": max(serie["corrente_pcc_a"]),
                "frequencia_min_hz": min(serie["frequencia_hz"]),
                "frequencia_max_hz": max(serie["frequencia_hz"]),
                "diesel_potencia_max_kw": max(serie["diesel_kw"]),
                "tempo_ligacao_gerador_s": _tempo_primeira_ligacao(eventos),
                "soc_inicial": serie["soc"][0],
                "soc_final": serie["soc"][-1],
            },
            "serie_temporal": serie,
        }
        if cfg.graficos_dir:
            resultado["graficos_saida"] = self.gerar_graficos(resultado, cfg.graficos_dir)
        if cfg.saida:
            saida = Path(cfg.saida).expanduser().resolve()
            saida.parent.mkdir(parents=True, exist_ok=True)
            saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
            resultado["arquivo_saida"] = str(saida)
        return resultado

    @staticmethod
    def _possui_diesel(documento: dict[str, Any]) -> bool:
        registros = documento.get("geradordiesel_info") or documento.get("gerador_diesel") or []
        if isinstance(registros, dict):
            return bool(registros)
        return isinstance(registros, list) and bool(registros) and isinstance(registros[0], dict)

    @staticmethod
    def _primeira_ordem(alvo: np.ndarray, tempo: np.ndarray, tau_s: float, inicial: float = 0.0) -> np.ndarray:
        saida = np.empty_like(alvo, dtype=float)
        saida[0] = inicial
        dt = float(tempo[1] - tempo[0])
        alpha = 1.0 - np.exp(-dt / tau_s)
        for i in range(1, len(alvo)):
            saida[i] = saida[i - 1] + alpha * (alvo[i] - saida[i - 1])
        return saida

    @staticmethod
    def _integrar(valores: np.ndarray, tempo: np.ndarray) -> float:
        trapezoid = getattr(np, "trapezoid", np.trapz)
        return float(trapezoid(valores, tempo))

    def _carregar_falha(self, documento: dict[str, Any], entrada: Path) -> tuple[dict[str, Any], list[str]]:
        avisos: list[str] = []
        candidatos: list[dict[str, Any]] = []
        for falha in documento.get("Falhas_sim") or []:
            if isinstance(falha, dict):
                candidatos.append(falha)

        caminho_falhas = self.configuracao.falhas
        if caminho_falhas:
            caminho = Path(caminho_falhas).expanduser()
            if caminho.exists():
                conteudo = json.loads(caminho.read_text(encoding="utf-8"))
                candidatos.extend(item for item in conteudo if isinstance(item, dict))
        else:
            candidatos.extend(self._falhas_do_projeto())

        for falha in candidatos:
            if falha.get("Tipo_Falha") != "Perda_String_FV":
                continue
            tempos = falha.get("T_falha") or []
            duracoes = falha.get("duracao_falha") or []
            if tempos and duracoes:
                return {
                    "tipo": "Perda_String_FV",
                    "id_pv": falha.get("id_pv", "PV_1"),
                    "inicio_s": float(tempos[0]),
                    "duracao_s": float(duracoes[0]),
                    "strings_totais": int((falha.get("strings_totais") or [self.configuracao.strings_fv])[0]),
                    "strings_perdidas": int((falha.get("strings_perdidas") or [self.configuracao.strings_perdidas])[0]),
                }, avisos

        avisos.append("Nenhum evento Perda_String_FV ativo foi encontrado; foi aplicado o cenário padrão de 0,5 s a 0,75 s.")
        return {
            "tipo": "Perda_String_FV",
            "id_pv": "PV_1",
            "inicio_s": 0.5,
            "duracao_s": 0.25,
            "strings_totais": self.configuracao.strings_fv,
            "strings_perdidas": self.configuracao.strings_perdidas,
        }, avisos

    @staticmethod
    def _falhas_do_projeto() -> list[dict[str, Any]]:
        raiz = Path(__file__).resolve().parents[2]
        caminho = raiz / "sim-stable" / "Arquivos_Temp_Json" / "Falhas_sim.json"
        if not caminho.exists():
            return []
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        return conteudo if isinstance(conteudo, list) else []

    @staticmethod
    def gerar_graficos(resultado: dict[str, Any], diretorio: str | Path) -> list[str]:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        pasta = Path(diretorio).expanduser().resolve()
        pasta.mkdir(parents=True, exist_ok=True)
        serie = resultado["serie_temporal"]
        tempo = np.asarray(serie["tempo_s"], dtype=float)
        ativo = np.asarray(serie["falha_ativa"], dtype=bool)
        inicio = float(resultado["contingencia"]["inicio_s"])
        fim = float(resultado["contingencia"]["fim_s"])

        def marcar_evento(ax: Any) -> None:
            if fim >= float(tempo[0]) and inicio <= float(tempo[-1]):
                ax.axvspan(inicio, fim, color="tab:red", alpha=0.16, label="Perda de strings FV")
                ax.axvline(inicio, color="tab:red", linestyle="--", linewidth=0.9)
                ax.axvline(fim, color="tab:green", linestyle="--", linewidth=0.9, label="Restabelecimento")
            tempo_ligacao = resultado.get("tempo_ligacao_gerador_s")
            if tempo_ligacao is not None:
                ax.axvline(
                    float(tempo_ligacao),
                    color="tab:purple",
                    linestyle=":",
                    linewidth=1.1,
                    label="Ligacao do gerador",
                )
            ax.grid(True, alpha=0.3)

        saidas: list[str] = []
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(tempo, serie["pv_kw"], label="FV", linewidth=1.1)
        axes[0].plot(tempo, serie["carga_kw"], label="Carga", linewidth=1.1)
        axes[0].plot(tempo, serie["bess_kw"], label="BESS (+ descarga)", linewidth=1.1)
        axes[0].plot(tempo, serie["rede_kw"], label="Rede (+ importação / - exportação)", linewidth=1.1)
        axes[0].set_ylabel("Potência [kW]")
        axes[0].set_title("Regime transitório — balanço de potência")
        marcar_evento(axes[0])
        axes[0].legend(ncol=2)
        axes[1].plot(tempo, serie["soc"], label="SOC", color="tab:purple")
        axes[1].set_ylabel("SOC [pu]")
        axes[1].set_xlabel("Tempo [s]")
        axes[1].set_ylim(0, 1)
        marcar_evento(axes[1])
        axes[1].legend()
        fig.tight_layout()
        caminho = pasta / "transitorio_potencias_soc.png"
        fig.savefig(caminho, dpi=150)
        plt.close(fig)
        saidas.append(str(caminho))

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(tempo, serie["tensao_pcc_pu"], label="Tensão PCC", color="tab:blue")
        axes[0].axhline(1.0, color="gray", linestyle=":", linewidth=0.9)
        axes[0].set_ylabel("Tensão [pu]")
        axes[0].set_title("Regime transitório — grandezas no PCC")
        marcar_evento(axes[0])
        axes[0].legend()
        axes[1].plot(tempo, serie["corrente_pcc_a"], label="Corrente PCC", color="tab:orange")
        axes[1].set_ylabel("Corrente [A]")
        axes[1].set_xlabel("Tempo [s]")
        marcar_evento(axes[1])
        axes[1].legend()
        fig.tight_layout()
        caminho = pasta / "transitorio_pcc.png"
        fig.savefig(caminho, dpi=150)
        plt.close(fig)
        saidas.append(str(caminho))

        if "diesel_kw" in serie:
            fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
            axes[0].plot(tempo, serie["rede_kw"], label="Rede", linewidth=1.1)
            axes[0].plot(tempo, serie["diesel_kw"], label="Diesel eletrico", linewidth=1.1)
            axes[0].plot(
                tempo,
                serie["potencia_mecanica_diesel_kw"],
                label="Diesel mecanico",
                linewidth=1.1,
            )
            axes[0].set_ylabel("Potencia [kW]")
            axes[0].set_title("Transitorio do gerador diesel conectado a rede")
            marcar_evento(axes[0])
            axes[0].legend(ncol=2)
            axes[1].plot(tempo, serie["frequencia_hz"], label="Frequencia", color="tab:orange")
            axes[1].plot(tempo, serie["tensao_pcc_pu"], label="Tensao PCC [pu]", color="tab:blue")
            axes[1].axhline(60.0, color="tab:orange", linestyle=":", linewidth=0.9)
            axes[1].set_ylabel("Hz / pu")
            axes[1].set_xlabel("Tempo [s]")
            marcar_evento(axes[1])
            axes[1].legend(ncol=2)
            fig.tight_layout()
            caminho = pasta / "transitorio_diesel.png"
            fig.savefig(caminho, dpi=150)
            plt.close(fig)
            saidas.append(str(caminho))
        return saidas


def _configuracao_simulacao(documento: dict[str, Any]) -> dict[str, Any]:
    estudos = documento.get("estudos") or {}
    if isinstance(estudos, dict):
        transitorio = estudos.get("transitorio") or estudos.get("transiente")
        if isinstance(transitorio, dict):
            return transitorio
    configuracoes = documento.get("Config_Simulacao") or []
    if isinstance(configuracoes, dict):
        configuracoes = [configuracoes]
    if isinstance(configuracoes, list):
        for configuracao in configuracoes:
            if not isinstance(configuracao, dict):
                continue
            tipo = str(configuracao.get("Tipo_Sim", "")).lower()
            if "trans" in tipo:
                return configuracao
        for configuracao in configuracoes:
            if isinstance(configuracao, dict):
                return configuracao
    return {}


def _primeiro(documento: dict[str, Any], chave: str) -> dict[str, Any]:
    registros = documento.get(chave) or []
    if isinstance(registros, dict):
        return registros
    if not isinstance(registros, list) or not registros or not isinstance(registros[0], dict):
        return {}
    return registros[0]


def _numero(valor: Any, padrao: float) -> float:
    if valor is None or valor == "":
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


def _pv_nominal(documento: dict[str, Any], padrao_kwp: float) -> float:
    painel = _primeiro(documento, "painel_info")
    if not painel:
        return float(padrao_kwp)
    return max(
        _numero(painel.get("Pmp"), padrao_kwp * 1000.0)
        * _quantidade(painel.get("quantidade", 1))
        / 1000.0,
        0.0,
    )


def _carga_transitoria(documento: dict[str, Any], padrao_kw: float) -> float:
    rede_teste = documento.get("rede_teste") or documento.get("transitorio") or {}
    if isinstance(rede_teste, dict) and rede_teste.get("carga_inicial_kw") is not None:
        return max(_numero(rede_teste.get("carga_inicial_kw"), padrao_kw), 0.0)
    carga = _primeiro(documento, "cargas_info")
    if carga.get("potencia_transitoria_kw") is not None:
        return max(_numero(carga.get("potencia_transitoria_kw"), padrao_kw), 0.0)
    if carga.get("s_instalada") is not None:
        fp = _numero(carga.get("fp"), 1.0)
        return max(
            _numero(carga.get("s_instalada"), padrao_kw * 1000.0)
            / 1000.0
            * fp
            * _quantidade(carga.get("quantidade", 1)),
            0.0,
        )
    return max(float(padrao_kw), 0.0)


def _soc(valor: Any, padrao: float) -> float:
    numero = _numero(valor, padrao * 100.0 if padrao <= 1 else padrao)
    return numero / 100.0 if numero > 1.0 else numero


def _bess_do_documento(documento: dict[str, Any]) -> BESS | None:
    dados = _primeiro(documento, "bateria_info")
    if not dados:
        return None
    quantidade = _quantidade(dados.get("quantidade", 1))
    parametros = ParametrosBESS(
        id_bess=str(dados.get("bateria_id") or "BESS_1"),
        capacidade_kwh=max(_numero(dados.get("capacidade_kwh"), 100.0) * quantidade, 0.001),
        potencia_max_carga_kw=max(_numero(dados.get("potencia_max_carga_kw"), 40.0) * quantidade, 0.0),
        potencia_max_descarga_kw=max(_numero(dados.get("potencia_max_descarga_kw"), 40.0) * quantidade, 0.0),
        soc_inicial=_soc(dados.get("soc_inicial"), 0.70),
        soc_minimo=_soc(dados.get("soc_min", dados.get("soc_minimo")), 0.10),
        soc_maximo=_soc(dados.get("soc_max", dados.get("soc_maximo")), 0.90),
        eficiencia_carga=_numero(dados.get("eficiencia_carga"), 0.95),
        eficiencia_descarga=_numero(dados.get("eficiencia_descarga"), 0.95),
        tensao_nominal_v=_numero(dados.get("tensao_nominal_v"), 480.0),
        resistencia_interna_ohm=_numero(dados.get("resistencia_interna_ohm"), 0.02),
    )
    return BESS(parametros)


def _comando_bess(residual_kw: float, bess: BESS) -> float:
    if residual_kw >= 0:
        return min(residual_kw, bess.parametros.potencia_max_descarga_kw)
    return max(residual_kw, -bess.parametros.potencia_max_carga_kw)


def _carga_no_instante(
    instante: float,
    carga_inicial_kw: float,
    eventos: tuple[EventoGeradorDiesel, ...],
) -> float:
    carga = carga_inicial_kw
    for evento in eventos:
        if evento.tipo in {"degrau_carga", "carga"} and evento.ativo(instante):
            carga = float(evento.carga_kw or 0.0)
    return max(carga, 0.0)


def _evento_carga_no_instante(
    instante: float,
    eventos: tuple[EventoGeradorDiesel, ...],
) -> EventoGeradorDiesel | None:
    ativos = [
        evento
        for evento in eventos
        if evento.tipo in {"degrau_carga", "carga"} and evento.ativo(instante)
    ]
    return ativos[-1] if ativos else None


def _evento_curto_no_instante(
    instante: float,
    eventos: tuple[EventoGeradorDiesel, ...],
) -> EventoGeradorDiesel | None:
    ativos = [
        evento
        for evento in eventos
        if evento.tipo in {"curto_circuito", "curto_circuito_3ph", "curto_3ph"}
        and evento.ativo(instante)
    ]
    return ativos[-1] if ativos else None


def _evento_ligacao_no_instante(
    instante: float,
    eventos: tuple[EventoGeradorDiesel, ...],
) -> EventoGeradorDiesel | None:
    """Retorna o evento que conecta o grupo diesel ao barramento/rede."""

    ativos = [
        evento
        for evento in eventos
        if evento.tipo in {
            "ligacao_gerador_rede",
            "ligacao_diesel_rede",
            "conexao_gerador",
            "entrada_gerador_rede",
        }
        and evento.ativo(instante)
    ]
    return ativos[-1] if ativos else None


def _tempo_primeira_ligacao(eventos: tuple[EventoGeradorDiesel, ...]) -> float | None:
    tempos = [
        float(evento.inicio_s)
        for evento in eventos
        if evento.tipo in {
            "ligacao_gerador_rede",
            "ligacao_diesel_rede",
            "conexao_gerador",
            "entrada_gerador_rede",
        }
    ]
    return min(tempos) if tempos else None


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return min(max(float(valor), float(minimo)), float(maximo))


__all__ = ["ConfiguracaoTransitorio", "TransitorioBessFV"]

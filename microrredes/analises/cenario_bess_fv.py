"""Cenário horário on-grid de FV + BESS com contingência de strings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any

from .fluxo_potencia import AnaliseFluxoPotencia, _importar_pandapower


SOLAR_PROFILE = (0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.20, 0.45, 0.70, 0.85, 0.95, 1.0, 1.0, 0.95, 0.85, 0.70, 0.50, 0.25, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0)
LOAD_PROFILE = (0.75, 0.70, 0.68, 0.68, 0.70, 0.75, 0.85, 0.95, 1.0, 1.05, 1.10, 1.08, 1.05, 1.0, 0.98, 1.0, 1.08, 1.15, 1.20, 1.15, 1.0, 0.90, 0.82, 0.78)


@dataclass(frozen=True)
class ConfiguracaoCenario:
    """Premissas editáveis do estudo diário."""

    consumo_diario_kwh: float = 650.0
    pv_kwp: float = 80.0
    bess_kwh: float = 100.0
    bess_kw: float = 40.0
    strings_fv: int = 16
    strings_perdidas: int = 4
    contingencia_inicio_h: int = 10
    contingencia_fim_h: int = 18
    soc_inicial: float = 0.50
    soc_minimo: float = 0.10
    eficiencia_carga: float = 0.95
    eficiencia_descarga: float = 0.95
    fator_potencia_carga: float = 0.95

    def __post_init__(self) -> None:
        if self.consumo_diario_kwh <= 0 or self.pv_kwp <= 0 or self.bess_kwh <= 0 or self.bess_kw <= 0:
            raise ValueError("Consumo, FV e BESS devem ser positivos")
        if self.strings_fv <= 0 or not 0 <= self.strings_perdidas <= self.strings_fv:
            raise ValueError("A quantidade de strings perdidas deve estar entre zero e strings_fv")
        if not 0 <= self.contingencia_inicio_h < self.contingencia_fim_h <= 24:
            raise ValueError("A janela de contingência deve estar entre 0 e 24 horas")
        if not 0 < self.soc_minimo < 1 or not self.soc_minimo <= self.soc_inicial <= 1:
            raise ValueError("SOC inicial e mínimo devem estar entre 0 e 1")
        if not 0 < self.eficiencia_carga <= 1 or not 0 < self.eficiencia_descarga <= 1:
            raise ValueError("As eficiências devem estar entre zero e um")
        if not 0 < self.fator_potencia_carga <= 1:
            raise ValueError("O fator de potência deve estar entre zero e um")


class CenarioBessFV:
    """Executa 24 fluxos de potência AC para o caso base e a contingência."""

    def __init__(self, configuracao: ConfiguracaoCenario | None = None) -> None:
        self.config = configuracao or ConfiguracaoCenario()

    def executar(self) -> dict[str, Any]:
        caso_base = self._simular(contingencia=False)
        caso_contingencia = self._simular(contingencia=True)
        return {
            "analise": "microrede_bess_fv_on_grid",
            "unidade_consumo": "kWh/dia",
            "configuracao": asdict(self.config),
            "premissas": {
                "operacao": "on-grid",
                "perfil_carga": "perfil horário normalizado para o consumo diário informado",
                "perfil_solar": "curva solar fixa de 24 horas",
                "convencao_rede_kw": "positivo importa da distribuidora; negativo exporta",
                "convencao_bateria_kw": "positivo descarrega; negativo carrega",
                "contingencia": "indisponibilidade de parte das strings durante a janela configurada",
            },
            "caso_base": caso_base["resumo"],
            "caso_contingencia": caso_contingencia["resumo"],
            "impacto_contingencia": {
                "delta_importacao_rede_kwh": caso_contingencia["resumo"]["energia_importada_rede_kwh"] - caso_base["resumo"]["energia_importada_rede_kwh"],
                "delta_exportacao_rede_kwh": caso_contingencia["resumo"]["energia_exportada_rede_kwh"] - caso_base["resumo"]["energia_exportada_rede_kwh"],
                "delta_energia_pv_disponivel_kwh": caso_contingencia["resumo"]["energia_pv_disponivel_kwh"] - caso_base["resumo"]["energia_pv_disponivel_kwh"],
                "delta_pico_importacao_kw": caso_contingencia["resumo"]["pico_importacao_rede_kw"] - caso_base["resumo"]["pico_importacao_rede_kw"],
            },
            "passos_horarios": {
                "caso_base": caso_base["passos"],
                "caso_contingencia": caso_contingencia["passos"],
            },
        }

    @staticmethod
    def gerar_graficos(resultado: dict[str, Any], diretorio: str | Path = "resultados") -> list[str]:
        """Gera figuras estáticas do estudo horário e da contingência."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pasta = Path(diretorio)
        pasta.mkdir(parents=True, exist_ok=True)
        base = resultado["passos_horarios"]["caso_base"]
        contingencia = resultado["passos_horarios"]["caso_contingencia"]
        horas = [item["hora"] for item in base]

        figura_regime, eixos = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
        ax = eixos[0, 0]
        ax.plot(horas, [item["carga_kw"] for item in base], label="Carga", linewidth=2)
        ax.plot(horas, [item["pv_disponivel_kw"] for item in base], label="FV disponível", linewidth=2)
        ax.plot(horas, [item["bateria_kw"] for item in base], label="BESS (+ descarga)", linewidth=2)
        ax.plot(horas, [item["rede_kw"] for item in base], label="Rede (+ importação)", linewidth=2)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_title("Regime permanente horário — caso base")
        ax.set_xlabel("Hora")
        ax.set_ylabel("Potência (kW)")
        ax.grid(alpha=0.25)
        ax.legend()

        ax = eixos[0, 1]
        ax.plot(horas, [item["soc_kwh"] for item in base], label="Base", linewidth=2)
        ax.plot(horas, [item["soc_kwh"] for item in contingencia], label="Contingência", linewidth=2)
        ax.axhline(resultado["configuracao"]["bess_kwh"] * resultado["configuracao"]["soc_minimo"], color="black", linestyle="--", linewidth=1, label="SOC mínimo")
        ax.set_title("Estado de carga do BESS")
        ax.set_xlabel("Hora")
        ax.set_ylabel("Energia (kWh)")
        ax.grid(alpha=0.25)
        ax.legend()

        ax = eixos[1, 0]
        ax.plot(horas, [item["rede_kw"] for item in base], label="Base", linewidth=2)
        ax.plot(horas, [item["rede_kw"] for item in contingencia], label="Contingência", linewidth=2)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.fill_between(horas, 0, [item["rede_kw"] for item in contingencia], alpha=0.12)
        ax.set_title("Intercâmbio com a distribuidora")
        ax.set_xlabel("Hora")
        ax.set_ylabel("Potência (kW) — + compra / − venda")
        ax.grid(alpha=0.25)
        ax.legend()

        ax = eixos[1, 1]
        ax.plot(horas, [item["tensao_pu_pcc"] for item in base], label="Tensão PCC — base", linewidth=2)
        ax.plot(horas, [item["tensao_pu_pcc"] for item in contingencia], label="Tensão PCC — contingência", linewidth=2)
        ax.axhline(1.05, color="black", linestyle="--", linewidth=0.8)
        ax.axhline(0.95, color="black", linestyle="--", linewidth=0.8)
        ax.set_title("Tensão no PCC e carregamento da linha")
        ax.set_xlabel("Hora")
        ax.set_ylabel("Tensão (pu)")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left")
        ax2 = ax.twinx()
        ax2.plot(horas, [item["carregamento_linha_percentual"] for item in contingencia], color="tab:red", linestyle=":", label="Linha — contingência")
        ax2.set_ylabel("Carregamento da linha (%)")

        caminho_regime = pasta / "regime_permanente_bess_fv.png"
        figura_regime.savefig(caminho_regime, dpi=160)
        plt.close(figura_regime)

        figura_contingencia, eixos = plt.subplots(2, 1, figsize=(14, 8), constrained_layout=True, sharex=True)
        ax = eixos[0]
        ax.plot(horas, [item["pv_bruta_kw"] for item in contingencia], label="FV bruta", linewidth=2)
        ax.plot(horas, [item["pv_disponivel_kw"] for item in contingencia], label="FV disponível", linewidth=2)
        ax.fill_between(horas, [item["pv_disponivel_kw"] for item in contingencia], [item["pv_bruta_kw"] for item in contingencia], alpha=0.25, label="Perda de strings")
        ax.set_title("Contingência — indisponibilidade de strings FV")
        ax.set_ylabel("Potência FV (kW)")
        ax.grid(alpha=0.25)
        ax.legend()

        ax = eixos[1]
        ax.plot(horas, [item["rede_kw"] for item in base], label="Rede — base", linewidth=2)
        ax.plot(horas, [item["rede_kw"] for item in contingencia], label="Rede — contingência", linewidth=2)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xlabel("Hora")
        ax.set_ylabel("Potência na rede (kW)")
        ax.grid(alpha=0.25)
        ax.legend()

        caminho_contingencia = pasta / "contingencia_strings_fv.png"
        figura_contingencia.savefig(caminho_contingencia, dpi=160)
        plt.close(figura_contingencia)
        return [str(caminho_regime), str(caminho_contingencia)]

    def _simular(self, contingencia: bool) -> dict[str, Any]:
        cfg = self.config
        carga = self._perfil_carga()
        soc_kwh = cfg.bess_kwh * cfg.soc_inicial
        passos: list[dict[str, Any]] = []

        for hora, carga_kw in enumerate(carga):
            pv_bruta_kw = cfg.pv_kwp * SOLAR_PROFILE[hora]
            contingencia_ativa = contingencia and cfg.contingencia_inicio_h <= hora < cfg.contingencia_fim_h
            fator_disponibilidade = 1.0 - cfg.strings_perdidas / cfg.strings_fv if contingencia_ativa else 1.0
            pv_disponivel_kw = pv_bruta_kw * fator_disponibilidade
            pv_perdida_kw = pv_bruta_kw - pv_disponivel_kw
            excedente_pv_kw = max(pv_disponivel_kw - carga_kw, 0.0)
            deficit_kw = max(carga_kw - pv_disponivel_kw, 0.0)
            bateria_kw = 0.0

            if excedente_pv_kw > 0:
                limite_potencia = min(cfg.bess_kw, excedente_pv_kw)
                limite_soc = max((cfg.bess_kwh - soc_kwh) / cfg.eficiencia_carga, 0.0)
                carga_bateria_kw = min(limite_potencia, limite_soc)
                bateria_kw = -carga_bateria_kw
                soc_kwh += carga_bateria_kw * cfg.eficiencia_carga
            elif hora in (18, 19, 20) and deficit_kw > 0:
                limite_potencia = min(cfg.bess_kw, deficit_kw)
                limite_soc = max((soc_kwh - cfg.bess_kwh * cfg.soc_minimo) * cfg.eficiencia_descarga, 0.0)
                descarga_bateria_kw = min(limite_potencia, limite_soc)
                bateria_kw = descarga_bateria_kw
                soc_kwh -= descarga_bateria_kw / cfg.eficiencia_descarga

            rede_kw = carga_kw - pv_disponivel_kw - bateria_kw
            tensao_pu, carregamento_linha = self._executar_fluxo_hora(carga_kw, pv_disponivel_kw, bateria_kw)
            passos.append(
                {
                    "hora": hora,
                    "carga_kw": round(carga_kw, 6),
                    "pv_bruta_kw": round(pv_bruta_kw, 6),
                    "pv_disponivel_kw": round(pv_disponivel_kw, 6),
                    "pv_perdida_kw": round(pv_perdida_kw, 6),
                    "bateria_kw": round(bateria_kw, 6),
                    "soc_kwh": round(soc_kwh, 6),
                    "rede_kw": round(rede_kw, 6),
                    "tensao_pu_pcc": round(tensao_pu, 6),
                    "carregamento_linha_percentual": round(carregamento_linha, 6),
                    "contingencia_ativa": contingencia_ativa,
                }
            )

        resumo = {
            "energia_carga_kwh": round(sum(item["carga_kw"] for item in passos), 6),
            "energia_pv_bruta_kwh": round(sum(item["pv_bruta_kw"] for item in passos), 6),
            "energia_pv_disponivel_kwh": round(sum(item["pv_disponivel_kw"] for item in passos), 6),
            "energia_pv_perdida_kwh": round(sum(item["pv_perdida_kw"] for item in passos), 6),
            "energia_bateria_carga_kwh": round(sum(max(-item["bateria_kw"], 0.0) for item in passos), 6),
            "energia_bateria_descarga_kwh": round(sum(max(item["bateria_kw"], 0.0) for item in passos), 6),
            "energia_importada_rede_kwh": round(sum(max(item["rede_kw"], 0.0) for item in passos), 6),
            "energia_exportada_rede_kwh": round(sum(max(-item["rede_kw"], 0.0) for item in passos), 6),
            "pico_importacao_rede_kw": round(max(item["rede_kw"] for item in passos), 6),
            "pico_exportacao_rede_kw": round(abs(min(item["rede_kw"] for item in passos)), 6),
            "soc_final_kwh": round(passos[-1]["soc_kwh"], 6),
            "tensao_minima_pu": round(min(item["tensao_pu_pcc"] for item in passos), 6),
            "tensao_maxima_pu": round(max(item["tensao_pu_pcc"] for item in passos), 6),
            "carregamento_maximo_linha_percentual": round(max(item["carregamento_linha_percentual"] for item in passos), 6),
            "rede_conectada_em_todos_os_passos": True,
        }
        return {"resumo": resumo, "passos": passos}

    def _perfil_carga(self) -> tuple[float, ...]:
        total_fatores = sum(LOAD_PROFILE)
        fator_kwh = self.config.consumo_diario_kwh / total_fatores
        return tuple(fator * fator_kwh for fator in LOAD_PROFILE)

    def _executar_fluxo_hora(self, carga_kw: float, pv_kw: float, bateria_kw: float) -> tuple[float, float]:
        pp = _importar_pandapower()
        net = AnaliseFluxoPotencia.criar_rede_demo()
        pcc = int(net.bus.index[net.bus.name == "PCC"][0])
        net.load.at[0, "p_mw"] = carga_kw / 1000.0
        net.load.at[0, "q_mvar"] = carga_kw * math.tan(math.acos(self.config.fator_potencia_carga)) / 1000.0
        pp.create_sgen(net, pcc, p_mw=pv_kw / 1000.0, q_mvar=0.0, name="FV")
        pp.create_sgen(net, pcc, p_mw=bateria_kw / 1000.0, q_mvar=0.0, name="BESS")
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=False, numba=False)
        return float(net.res_bus.vm_pu.at[pcc]), float(net.res_line.loading_percent.iloc[0])


__all__ = ["ConfiguracaoCenario", "CenarioBessFV"]

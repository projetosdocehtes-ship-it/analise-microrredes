"""Interface de linha de comando para as análises do projeto."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analises.cenario_bess_fv import ConfiguracaoCenario, CenarioBessFV
from .analises.falhas import AnaliseFalhas
from .analises.fluxo_potencia import AnaliseFluxoPotencia, DependenciaOpcionalAusente
from .analises.fundamentais import AnaliseFundamental, PerfilConsumo
from .analises.transitorio_bess_fv import ConfiguracaoTransitorio, TransitorioBessFV
from .analises.graficos_interativos import gerar_html_interativo
from .analises.regime_permanente import ConfiguracaoRegimePermanente, RegimePermanente
from .analises.transitorio_gerador_diesel import ConfiguracaoTransitorioDiesel, TransitorioGeradorDiesel
from .dados.tarifas_aneel import ClienteTarifasANEEL, ErroTarifasANEEL


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value).__name__}")


def _imprimir(resultado: dict[str, Any]) -> None:
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=_json_default))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m microrredes",
        description="Executa análises independentes de uma microrrede.",
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    fluxo = subparsers.add_parser("fluxo-potencia", help="Executa o fluxo de potência AC.")
    entrada_fluxo = fluxo.add_mutually_exclusive_group()
    entrada_fluxo.add_argument("--entrada", default=None, help="Arquivo JSON próprio do estudo de regime permanente.")
    entrada_fluxo.add_argument("--demo", action="store_true", help="Usa a rede mínima de demonstração (padrão sem --entrada).")
    fluxo.add_argument("--saida", default=None, help="Arquivo JSON opcional para salvar o resultado.")

    falhas = subparsers.add_parser("falhas", help="Executa curto-circuito independente do fluxo.")
    falhas.add_argument("--tipo", choices=("3ph", "2ph", "1ph"), default="3ph")
    falhas.add_argument("--caso", choices=("max", "min"), default="max")
    falhas.add_argument("--demo", action="store_true", default=True, help="Usa a rede mínima de demonstração.")

    cenario = subparsers.add_parser("cenario-bess-fv", help="Executa cenário horário on-grid de FV+BESS com contingência.")
    cenario.add_argument("--consumo-dia-kwh", type=float, default=650.0)
    cenario.add_argument("--pv-kwp", type=float, default=80.0)
    cenario.add_argument("--bess-kwh", type=float, default=100.0)
    cenario.add_argument("--bess-kw", type=float, default=40.0)
    cenario.add_argument("--strings-fv", type=int, default=16)
    cenario.add_argument("--strings-perdidas", type=int, default=4)
    cenario.add_argument("--contingencia-inicio", type=int, default=10, metavar="HORA")
    cenario.add_argument("--contingencia-fim", type=int, default=18, metavar="HORA")
    cenario.add_argument("--saida", default=None, help="Arquivo JSON opcional para salvar o resultado.")
    regime = subparsers.add_parser("regime-permanente", help="Executa fluxo de potencia horario com curva de carga CSV.")
    regime.add_argument("--entrada", required=True, help="JSON proprio do estudo de regime permanente.")
    regime.add_argument("--curva-carga", default=None, help="CSV opcional; sobrescreve cargas_info.curva_carga.")
    regime.add_argument("--periodo", choices=("24h", "ano"), default=None, help="Horizonte; se omitido, usa estudos.regime_permanente do JSON.")
    regime.add_argument("--tipo-dia", choices=("util", "fim_semana"), default=None, help="Perfil; se omitido, usa estudos.regime_permanente do JSON.")
    regime.add_argument("--dia-semana", type=int, choices=range(7), default=None, help="Dia ISO: 0=segunda, 6=domingo.")
    regime.add_argument("--ano", type=int, default=None, help="Ano de referência; se omitido, usa o JSON.")
    regime.add_argument("--horas", type=int, default=None, help="Limita o horizonte; util para validacoes e estudos parciais.")
    regime.add_argument("--escala-carga", type=float, default=None, help="Multiplicador da demanda do CSV.")
    regime.add_argument(
        "--tempo-operacao-gerador-h",
        type=float,
        default=None,
        help="Limite acumulado de horas de operação do gerador no horizonte.",
    )
    regime.add_argument("--saida", default=None, help="Arquivo JSON de saida.")
    diesel = subparsers.add_parser("transitorio-gerador-diesel", help="Testa o gerador diesel isolado em modo offgrid.")
    diesel.add_argument("--entrada", required=True, help="JSON proprio do teste do gerador diesel.")
    diesel.add_argument("--saida", default=None, help="Arquivo JSON de saida.")
    cenario.add_argument("--graficos-dir", default=None, help="Pasta opcional para salvar os gráficos PNG.")

    transitorio = subparsers.add_parser("transitorio-bess-fv", help="Executa simulação transitória em segundos a partir de Entradas.Json.")
    transitorio.add_argument("--entrada", required=True, help="Caminho do Entradas.Json usado no cenário.")
    transitorio.add_argument("--consumo-dia-kwh", type=float, default=650.0)
    transitorio.add_argument("--pv-kwp", type=float, default=80.0)
    transitorio.add_argument("--bess-kwh", type=float, default=100.0)
    transitorio.add_argument("--bess-kw", type=float, default=40.0)
    transitorio.add_argument("--strings-fv", type=int, default=16)
    transitorio.add_argument("--strings-perdidas", type=int, default=4)
    transitorio.add_argument("--falhas", default=None, help="Arquivo opcional Falhas_sim.json.")
    transitorio.add_argument("--forcar-on-grid", action="store_true", help="Executa on-grid mesmo se conectado_rede estiver false.")
    transitorio.add_argument("--saida", default=None, help="Arquivo JSON de saída.")
    transitorio.add_argument("--graficos-dir", default=None, help="Pasta de saída dos gráficos PNG.")
    transitorio.add_argument("--html-interativo", default=None, help="Arquivo HTML offline com valores no cursor e zoom.")

    fundamentais = subparsers.add_parser("fundamentais", help="Calcula custos tarifários com TE/TUSD e ICMS.")
    fundamentais.add_argument("--distribuidora", default="EQUATORIAL GO")
    fundamentais.add_argument("--grupo", default="A4")
    fundamentais.add_argument("--icms", type=float, default=0.0, help="Alíquota decimal, por exemplo 0.19 para 19%%.")
    fundamentais.add_argument("--energia-ponta", type=float, default=0.0, metavar="KWH")
    fundamentais.add_argument("--energia-fora-ponta", type=float, default=0.0, metavar="KWH")
    fundamentais.add_argument("--demanda-ponta", type=float, default=0.0, metavar="KW")
    fundamentais.add_argument("--demanda-fora-ponta", type=float, default=0.0, metavar="KW")
    fundamentais.add_argument("--usar-fallback", action="store_true", help="Permite dados locais explicitamente marcados como fallback.")
    fundamentais.add_argument("--cache-tarifas", default=None, help="Caminho do cache local de tarifas.")
    fundamentais.add_argument("--ttl-cache-dias", type=float, default=7.0, help="Validade do cache antes de ser marcado como expirado.")
    fundamentais.add_argument("--nao-usar-cache", action="store_true", help="Desabilita a leitura do cache local.")
    fundamentais.add_argument("--nao-atualizar-cache", action="store_true", help="Não grava respostas online no cache.")
    fundamentais.add_argument("--nao-usar-cache-expirado", action="store_true", help="Falha se o cache estiver vencido e a ANEEL estiver indisponível.")
    fundamentais.add_argument("--timeout", type=float, default=30.0)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        if args.comando == "fluxo-potencia":
            analise = AnaliseFluxoPotencia()
            resultado = analise.executar_arquivo(args.entrada) if args.entrada else analise.executar_demo()
            if args.saida:
                caminho = Path(args.saida)
                caminho.parent.mkdir(parents=True, exist_ok=True)
                resultado["arquivo_saida"] = str(caminho)
                caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
            _imprimir(resultado)
            return 0

        if args.comando == "falhas":
            _imprimir(AnaliseFalhas().executar_demo(tipo=args.tipo, caso=args.caso))
            return 0

        if args.comando == "cenario-bess-fv":
            resultado = CenarioBessFV(
                ConfiguracaoCenario(
                    consumo_diario_kwh=args.consumo_dia_kwh,
                    pv_kwp=args.pv_kwp,
                    bess_kwh=args.bess_kwh,
                    bess_kw=args.bess_kw,
                    strings_fv=args.strings_fv,
                    strings_perdidas=args.strings_perdidas,
                    contingencia_inicio_h=args.contingencia_inicio,
                    contingencia_fim_h=args.contingencia_fim,
                )
            ).executar()
            if args.graficos_dir:
                resultado["graficos_saida"] = CenarioBessFV.gerar_graficos(resultado, args.graficos_dir)
            if args.saida:
                caminho = Path(args.saida)
                caminho.parent.mkdir(parents=True, exist_ok=True)
                caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
                resultado["arquivo_saida"] = str(caminho)
            _imprimir(resultado)
            return 0

        if args.comando == "regime-permanente":
            configuracao_arquivo = ConfiguracaoRegimePermanente.from_entrada(args.entrada)
            resultado = RegimePermanente(
                ConfiguracaoRegimePermanente(
                    entrada=args.entrada,
                    periodo=args.periodo or configuracao_arquivo.periodo,
                    tipo_dia=args.tipo_dia or configuracao_arquivo.tipo_dia,
                    ano=args.ano if args.ano is not None else configuracao_arquivo.ano,
                    horas=args.horas if args.horas is not None else configuracao_arquivo.horas,
                    curva_carga=args.curva_carga or configuracao_arquivo.curva_carga,
                    escala_carga=args.escala_carga if args.escala_carga is not None else configuracao_arquivo.escala_carga,
                    dia_semana=args.dia_semana if args.dia_semana is not None else configuracao_arquivo.dia_semana,
                    tempo_operacao_gerador_h=(
                        args.tempo_operacao_gerador_h
                        if args.tempo_operacao_gerador_h is not None
                        else configuracao_arquivo.tempo_operacao_gerador_h
                    ),
                )
            ).executar()
            if args.saida:
                caminho = Path(args.saida)
                caminho.parent.mkdir(parents=True, exist_ok=True)
                resultado["arquivo_saida"] = str(caminho)
                caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
            _imprimir(resultado)
            return 0

        if args.comando == "transitorio-gerador-diesel":
            resultado = TransitorioGeradorDiesel(
                ConfiguracaoTransitorioDiesel.from_json(args.entrada)
            ).executar()
            if args.saida:
                caminho = Path(args.saida)
                caminho.parent.mkdir(parents=True, exist_ok=True)
                resultado["arquivo_saida"] = str(caminho)
                caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
            _imprimir(resultado)
            return 0

        if args.comando == "transitorio-bess-fv":
            resultado = TransitorioBessFV(
                ConfiguracaoTransitorio(
                    entrada=args.entrada,
                    consumo_diario_kwh=args.consumo_dia_kwh,
                    pv_kwp=args.pv_kwp,
                    bess_kwh=args.bess_kwh,
                    bess_kw=args.bess_kw,
                    strings_fv=args.strings_fv,
                    strings_perdidas=args.strings_perdidas,
                    forcar_on_grid=args.forcar_on_grid,
                    falhas=args.falhas,
                    saida=args.saida,
                    graficos_dir=args.graficos_dir,
                )
            ).executar()
            if args.html_interativo:
                resultado["grafico_interativo"] = gerar_html_interativo(resultado, args.html_interativo)
            _imprimir(resultado)
            return 0

        if args.comando == "fundamentais":
            snapshot = ClienteTarifasANEEL(
                distribuidora=args.distribuidora,
                grupo=args.grupo,
                timeout=args.timeout,
                permitir_fallback=args.usar_fallback,
                cache_path=args.cache_tarifas,
                cache_ttl_days=args.ttl_cache_dias,
                usar_cache=not args.nao_usar_cache,
                permitir_cache_expirado=not args.nao_usar_cache_expirado,
                atualizar_cache=not args.nao_atualizar_cache,
            ).carregar()
            perfil = PerfilConsumo(
                energia_ponta_kwh=args.energia_ponta,
                energia_fora_ponta_kwh=args.energia_fora_ponta,
                demanda_ponta_kw=args.demanda_ponta,
                demanda_fora_ponta_kw=args.demanda_fora_ponta,
            )
            resultado = AnaliseFundamental(snapshot, icms=args.icms).comparar_modalidades(perfil)
            _imprimir(resultado)
            return 0
    except (DependenciaOpcionalAusente, ErroTarifasANEEL, FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}")
        return 2

    return 2

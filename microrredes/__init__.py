"""Camada pública do projeto de análises de microrredes."""

__version__ = "0.1.0"

from .analises.falhas import AnaliseFalhas
from .analises.fluxo_potencia import AnaliseFluxoPotencia
from .analises.fundamentais import AnaliseFundamental, PerfilConsumo
from .analises.cenario_bess_fv import ConfiguracaoCenario, CenarioBessFV
from .analises.regime_permanente import ConfiguracaoRegimePermanente, ErroPerfilCarga, PerfilCargaHoraria, RegimePermanente
from .analises.transitorio_gerador_diesel import (
    ConfiguracaoGeradorDiesel,
    ConfiguracaoTransitorioDiesel,
    EventoGeradorDiesel,
    TransitorioGeradorDiesel,
)
from .analises.transitorio_eletrolisador_pem import (
    ConfiguracaoTransitorioEletrolisadorPEM,
    EventoCorrenteEletrolisadorPEM,
    TransitorioEletrolisadorPEM,
)
from .analises.transitorio_ciclo_hidrogenio import (
    ConfiguracaoTransitorioCicloHidrogenio,
    EventoCorrenteCicloHidrogenio,
    TransitorioCicloHidrogenio,
    comparar_geradores_hidrogenio,
)
from .dados.tarifas_aneel import ClienteTarifasANEEL, TarifaSnapshot

__all__ = [
    "AnaliseFalhas",
    "AnaliseFluxoPotencia",
    "AnaliseFundamental",
    "ConfiguracaoCenario",
    "CenarioBessFV",
    "ConfiguracaoRegimePermanente",
    "ErroPerfilCarga",
    "PerfilCargaHoraria",
    "RegimePermanente",
    "ConfiguracaoGeradorDiesel",
    "ConfiguracaoTransitorioDiesel",
    "EventoGeradorDiesel",
    "TransitorioGeradorDiesel",
    "ConfiguracaoTransitorioEletrolisadorPEM",
    "EventoCorrenteEletrolisadorPEM",
    "TransitorioEletrolisadorPEM",
    "ConfiguracaoTransitorioCicloHidrogenio",
    "EventoCorrenteCicloHidrogenio",
    "TransitorioCicloHidrogenio",
    "comparar_geradores_hidrogenio",
    "ClienteTarifasANEEL",
    "PerfilConsumo",
    "TarifaSnapshot",
]

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionConfig:
    use_ema: bool = True
    ema_above: bool = True
    ema_below: bool = False

    use_rsi: bool = True
    rsi_above: bool = True
    rsi_below: bool = False

    use_atr: bool = False
    atr_above: bool = False
    atr_below: bool = False

    use_adx: bool = False
    adx_above: bool = False

    use_session: bool = False
    session_start: int = 0
    session_end: int = 24

    use_weekday: bool = False
    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True

    use_prev_high: bool = False
    use_prev_low: bool = False

    use_round_number: bool = False

    use_fvg: bool = False
    use_bos: bool = False
    use_choch: bool = False
    use_orderblock: bool = False
    use_liquidity: bool = False
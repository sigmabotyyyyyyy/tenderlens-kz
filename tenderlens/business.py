"""Illustrative project economics, independent of procurement price analysis.

Inputs are assumptions supplied by a user, not market estimates. Payback assumes
the same clients, price and expenses every month, starting in month one.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext


@dataclass(frozen=True)
class BusinessInputs:
    clients: int = 5
    monthly_price: Decimal = Decimal("20000")
    fixed_costs: Decimal = Decimal("30000")
    cost_per_client: Decimal = Decimal("1000")
    initial_investment: Decimal = Decimal("100000")
    owner_pay: Decimal = Decimal("0")
    tax_reserve_percent: Decimal = Decimal("0")

    def __post_init__(self):
        if type(self.clients) is not int or not 0 <= self.clients <= 100000:
            raise ValueError("Число клиентов должно быть целым от 0 до 100 000.")
        for name in ("monthly_price", "fixed_costs", "cost_per_client", "initial_investment", "owner_pay", "tax_reserve_percent"):
            raw = getattr(self, name)
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                raise ValueError("Вводные должны быть конечными неотрицательными числами.") from None
            maximum = Decimal(100) if name == "tax_reserve_percent" else Decimal("1000000000")
            if not value.is_finite() or not 0 <= value <= maximum:
                raise ValueError("Расходы и цена: от 0 до 1 млрд ₸; резерв: от 0 до 100%.")
            if value.as_tuple().exponent < -2:
                raise ValueError("Используйте не больше двух знаков после запятой.")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class BusinessResult:
    revenue: Decimal
    variable_costs: Decimal
    tax_reserve: Decimal
    total_costs: Decimal
    monthly_profit: Decimal
    contribution_per_client: Decimal
    break_even_clients: int | None
    payback_months: int | None
    cash_after_year: Decimal


def calculate_business(inputs: BusinessInputs) -> BusinessResult:
    with localcontext() as context:
        context.prec = 64
        revenue = inputs.monthly_price * inputs.clients
        variable = inputs.cost_per_client * inputs.clients
        reserve = revenue * inputs.tax_reserve_percent / 100
        fixed = inputs.fixed_costs + inputs.owner_pay
        costs = fixed + variable + reserve
        profit = revenue - costs
        contribution = inputs.monthly_price * (1 - inputs.tax_reserve_percent / 100) - inputs.cost_per_client
        if fixed == 0:
            break_even = 0
        elif contribution > 0:
            break_even = int((fixed / contribution).to_integral_value(rounding=ROUND_CEILING))
        else:
            break_even = None
        if inputs.initial_investment == 0:
            payback = 0
        elif profit > 0:
            payback = int((inputs.initial_investment / profit).to_integral_value(rounding=ROUND_CEILING))
        else:
            payback = None
        return BusinessResult(revenue, variable, reserve, costs, profit, contribution, break_even,
                              payback, profit * 12 - inputs.initial_investment)

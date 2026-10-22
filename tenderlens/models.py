from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

CSV_FIELDS = (
    "item_id", "contract_id", "contract_date", "buyer_id", "supplier_id",
    "product_name", "paper_format", "density_g_m2", "sheets_per_pack", "unit",
    "quantity", "unit_price", "currency", "vat_basis", "delivery_basis",
    "delivery_region", "source_url",
)


@dataclass(frozen=True, slots=True)
class Item:
    item_id: str
    contract_id: str
    contract_date: date
    buyer_id: str
    supplier_id: str
    product_name: str
    paper_format: str
    density_g_m2: int
    sheets_per_pack: int
    unit: str
    quantity: int
    unit_price: Decimal
    currency: str
    vat_basis: str
    delivery_basis: str
    delivery_region: str
    source_url: str = ""

    def to_row(self) -> dict:
        row = asdict(self)
        row["contract_date"] = self.contract_date.isoformat()
        row["unit_price"] = str(self.unit_price)
        return row

    @classmethod
    def from_row(cls, row: dict) -> "Item":
        values = {key: row[key] for key in CSV_FIELDS}
        values["contract_date"] = date.fromisoformat(str(values["contract_date"]))
        values["unit_price"] = Decimal(str(values["unit_price"]))
        for key in ("density_g_m2", "sheets_per_pack", "quantity"):
            values[key] = int(values[key])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    window_days: int = 180
    min_comparable_contracts: int = 20
    price_ratio_threshold: Decimal = Decimal("1.50")
    algorithm_version: str = "median_v1"
    quantity_min_ratio: Decimal = Decimal("0.50")
    quantity_max_ratio: Decimal = Decimal("2.00")

    def __post_init__(self):
        try:
            for key in ("price_ratio_threshold", "quantity_min_ratio", "quantity_max_ratio"):
                object.__setattr__(self, key, Decimal(str(getattr(self, key))))
        except InvalidOperation:
            raise ValueError("Параметры цены и количества должны быть числами") from None
        if type(self.window_days) is not int or not 30 <= self.window_days <= 365:
            raise ValueError("Окно анализа должно быть целым числом от 30 до 365 дней")
        if type(self.min_comparable_contracts) is not int or not 5 <= self.min_comparable_contracts <= 100:
            raise ValueError("Минимум аналогов должен быть целым числом от 5 до 100")
        if not self.price_ratio_threshold.is_finite() or not Decimal("1.10") <= self.price_ratio_threshold <= 5:
            raise ValueError("Порог цены должен быть от 1.10 до 5.00")
        if (self.quantity_min_ratio, self.quantity_max_ratio) != (Decimal("0.5"), Decimal("2")):
            raise ValueError("В версии 1 диапазон количества фиксирован: 0.5–2.0")
        if self.algorithm_version not in ("median_v1", "baseline_v1"):
            raise ValueError("Неизвестная версия алгоритма")

    def to_dict(self) -> dict:
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class ContractPrice:
    contract_id: str
    price: Decimal


@dataclass(frozen=True, slots=True)
class ComparableSet:
    items: tuple[Item, ...]
    contract_prices: tuple[ContractPrice, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    item_id: str
    status: str
    reference_price: Decimal | None
    ratio: Decimal | None
    deviation_percent: Decimal | None
    comparable_contracts_count: int
    comparable_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationError:
    row_number: int
    item_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    items: tuple[Item, ...]
    errors: tuple[ValidationError, ...]
    warnings: tuple[str, ...]

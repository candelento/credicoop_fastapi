from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


def money(value):
    if isinstance(value, (float, bool)):
        raise ValueError('Ingresar monto como texto decimal con punto: "1234.56".')
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Monto inválido.') from None
    if not d.is_finite() or d <= 0 or d >= Decimal('10000000000000') or d != d.quantize(Decimal('.01')):
        raise ValueError('Monto positivo con hasta 13 enteros y 2 decimales.')
    return format(d, '.2f')


def bank_date(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        return datetime.strptime(value, '%Y%m%d').date().isoformat()
    return value


Money = Annotated[str, BeforeValidator(money)]
BankDate = Annotated[date, BeforeValidator(bank_date)]
CBU = Annotated[str, Field(pattern=r'^\d{22}$')]
CUI = Annotated[str, Field(pattern=r'^\d{11}$')]
Origin = Annotated[str, Field(min_length=1, max_length=36, pattern=r'^[A-Za-z0-9_-]+$')]
DocType = Literal['CUIT', 'CUIL', 'CDI', 'DNI', 'LC', 'PE', 'CI', 'LE']
Concept = Literal['ALQ', 'CUO', 'EXP', 'FAC', 'PRE', 'SEG', 'HON', 'VAR', 'OIH', 'BRH', 'SON', 'APC', 'ROP', 'SIS', 'ESE', 'HAB']
Text100 = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9 ]+$')]
Mail = Annotated[str, Field(min_length=3, max_length=150, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')]
FCI_SIGNER_DNI = '44379155'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class LoginRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class UserCreateRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: Annotated[str, Field(min_length=3, max_length=64, pattern=r'^[A-Za-z0-9_.-]+$')]
    password: Annotated[str, Field(min_length=12, max_length=256)]
    role: Literal['admin', 'user'] = 'user'


class UserUpdateRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    password: Annotated[str, Field(min_length=12, max_length=256)] | None = None
    role: Literal['admin', 'user'] | None = None
    active: bool | None = None

    @model_validator(mode='after')
    def require_change(self):
        if not any(getattr(self, name) is not None for name in ('password', 'role', 'active')):
            raise ValueError('Indicar al menos un dato para actualizar.')
        return self


class PasswordChangeRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=12, max_length=256)]


class Signer(StrictModel):
    documento: Annotated[str, Field(pattern=r'^\d{1,11}$')]
    documentoTipo: DocType = 'DNI'


class TransferBeneficiary(StrictModel):
    cbuCvu: CBU
    esCuentaPropia: Literal['S', 'N', 'C'] = 'N'
    monto: Money
    moneda: Literal['ARS'] = 'ARS'
    concepto: Concept = 'VAR'
    cui: CUI
    nombre: Text100
    observaciones: Annotated[str, Field(max_length=60, pattern=r'^[A-Za-z0-9 ]*$')] | None = None
    referenciaConcepto: Annotated[str, Field(max_length=12, pattern=r'^[A-Za-z0-9 ]*$')] | None = None
    mails: list[Mail] = Field(default_factory=list, max_length=3)


class SignedInstruction(StrictModel):
    idOrigen: Origin
    cbuCuentaDebito: CBU
    # El banco lo considera opcional; [] permite que BIE resuelva el esquema vigente.
    operadoresFirmantes: list[Signer] = Field(default_factory=list)


class TransferRequest(SignedInstruction):
    fechaPago: BankDate | None = None
    beneficiarios: list[TransferBeneficiary] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def batch_cbu_only(self):
        if len(self.beneficiarios) > 1 and any(b.cbuCvu.startswith('000') for b in self.beneficiarios):
            raise ValueError('Las transferencias múltiples admiten CBU; para CVU usar una operación individual.')
        return self


class Echeq(StrictModel):
    monto: Money
    fechaPago: BankDate
    motivoPago: Annotated[str, Field(min_length=1, pattern=r'^[A-Za-z0-9 ]+$')]
    caracter: Literal['1'] = '1'
    modo: Literal['1'] = '1'
    beneficiarioNombre: Text100
    beneficiarioDocumentoTipo: Literal['CUIT', 'CUIL', 'CDI'] = 'CUIT'
    beneficiarioDocumento: CUI
    concepto: Literal['ALQ', 'CUO', 'EXP', 'FAC', 'PRE', 'SEG', 'HON', 'VAR'] = 'VAR'
    tipoCheque: Literal['ECHC', 'ECHD']
    numeroCheque: int | None = Field(default=None, ge=1, le=99999999)
    mails: list[Mail] = Field(default_factory=list)


class EcheqRequest(SignedInstruction):
    echeqs: list[Echeq] = Field(min_length=1)

    @model_validator(mode='after')
    def consistent_chequebook(self):
        if len({x.numeroCheque is None for x in self.echeqs}) > 1:
            raise ValueError('No mezclar eCheqs con número de cheque y sin número.')
        return self


EcheqAction = Literal['ACEPTAR', 'DEPOSITAR', 'ENDOSAR', 'PONER-EN-CUSTODIA']


class EcheqManagementBeneficiary(StrictModel):
    documento: CUI
    documentoTipo: Literal['CUIT', 'CUIL', 'CDI']


class EcheqManagementItem(StrictModel):
    idCheque: Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9]+$')] | None = None
    cmc7: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^\d+$')] | None = None
    fechaPago: BankDate | None = None
    monto: Money | None = None

    @model_validator(mode='after')
    def require_identifier(self):
        if not self.idCheque and not self.cmc7:
            raise ValueError('Informar idCheque o cmc7 para cada eCheq.')
        return self


class EcheqManagementRequest(StrictModel):
    idOrigen: Origin
    cbuCuenta: CBU
    accion: EcheqAction
    operadoresFirmantes: list[Signer] = Field(default_factory=list)
    echeqs: list[EcheqManagementItem] = Field(min_length=1, max_length=100)
    tipoEndoso: Literal['NOM'] | None = None
    beneficiario: EcheqManagementBeneficiary | None = None

    @model_validator(mode='after')
    def validate_action_fields(self):
        if self.accion in ('DEPOSITAR', 'PONER-EN-CUSTODIA'):
            if any(item.fechaPago is None or item.monto is None for item in self.echeqs):
                raise ValueError('Para depositar o poner en custodia, informar fechaPago y monto de cada eCheq.')
        elif any(item.fechaPago is not None or item.monto is not None for item in self.echeqs):
            raise ValueError('fechaPago y monto sólo se informan para depósito o custodia.')
        if self.accion == 'ENDOSAR':
            if self.tipoEndoso is None or self.beneficiario is None:
                raise ValueError('Para endosar, informar tipoEndoso NOM y beneficiario.')
        elif self.tipoEndoso is not None or self.beneficiario is not None:
            raise ValueError('tipoEndoso y beneficiario sólo se informan al endosar.')
        return self


class EcheqListFilter(StrictModel):
    gestion: Annotated[str, Field(min_length=1, max_length=30, pattern=r'^[A-Z_-]+$')] | None = None
    estado: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Z_-]+$')] | None = None
    idCheque: Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9]+$')] | None = None
    cmc7: Annotated[str, Field(min_length=1, max_length=40, pattern=r'^\d+$')] | None = None
    numeroCheque: Annotated[str, Field(min_length=1, max_length=20, pattern=r'^\d+$')] | None = None
    cuitCuilCdi: CUI | None = None
    fechaEmisionDesde: BankDate | None = None
    fechaEmisionHasta: BankDate | None = None
    fechaPagoDesde: BankDate | None = None
    fechaPagoHasta: BankDate | None = None
    cbuEmisor: CBU | None = None
    moneda: Literal['ARS', 'USD'] | None = None
    pagina: int = Field(default=1, ge=1, le=100000)
    limite: int = Field(default=20, ge=1, le=1000)

    @model_validator(mode='after')
    def validate_date_ranges(self):
        for start, end in ((self.fechaEmisionDesde, self.fechaEmisionHasta),
                           (self.fechaPagoDesde, self.fechaPagoHasta)):
            if (start is None) != (end is None):
                raise ValueError('Informar las dos fechas de cada rango o ninguna.')
            if start is not None and start > end:
                raise ValueError('La fecha desde debe ser menor o igual a la fecha hasta.')
        return self


class EcheqListRequest(StrictModel):
    idOrigen: Origin
    filtro: EcheqListFilter


class FciAccount(StrictModel):
    tipoCuenta: Annotated[str, Field(min_length=1, max_length=10, pattern=r'^[A-Za-z0-9]+$')]
    sucursalCuenta: Annotated[str, Field(min_length=1, max_length=10, pattern=r'^\d+$')]
    numeroCuenta: Annotated[str, Field(min_length=1, max_length=30, pattern=r'^[0-9/]+$')]


class FciSubscriptionDetails(StrictModel):
    codigoFondo: Annotated[str, Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9_-]+$')]
    moneda: Literal['ARS', 'USD']
    monto: Money
    avanzarTestVencido: bool
    aceptarRiesgoExcedido: bool


class FciSubscriptionRequest(StrictModel):
    idOrigen: Origin
    cbuCuentaDebito: CBU
    cuentaComitente: FciAccount
    solicitudSuscripcion: FciSubscriptionDetails


def positive_units(value):
    if isinstance(value, bool):
        raise ValueError('Cantidad de cuotapartes inválida.')
    try:
        units = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Cantidad de cuotapartes inválida.') from None
    if (not units.is_finite() or units <= 0 or units >= Decimal('1000000000000')
            or units != units.quantize(Decimal('.00000001'))):
        raise ValueError('Cuotapartes positivas con hasta 12 enteros y 8 decimales.')
    return units


FciUnits = Annotated[Decimal, BeforeValidator(positive_units)]


class FciRedemptionDetails(StrictModel):
    codigoFondo: Annotated[str, Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9_-]+$')]
    moneda: Literal['ARS', 'USD']
    monto: Money | None = None
    cuotapartes: FciUnits | None = None

    @model_validator(mode='after')
    def exactly_one_amount_or_units(self):
        if (self.monto is None) == (self.cuotapartes is None):
            raise ValueError('Informar exactamente uno: monto o cuotapartes.')
        return self


class FciRedemptionRequest(StrictModel):
    idOrigen: Origin
    cbuCuentaCredito: CBU
    cuentaComitente: FciAccount
    solicitudRescate: FciRedemptionDetails


class FciPositionRequest(StrictModel):
    cuentaComitente: FciAccount


class FciMovementsRequest(StrictModel):
    cuentaComitente: FciAccount
    fechaDesde: BankDate
    fechaHasta: BankDate

    @model_validator(mode='after')
    def valid_date_range(self):
        if self.fechaDesde > self.fechaHasta:
            raise ValueError('fechaDesde debe ser menor o igual a fechaHasta.')
        return self


class OrderDebitAccount(StrictModel):
    cbuCuentaDebito: CBU


def instruction_payload(instruction: TransferRequest | EcheqRequest, adherente: int, today: date) -> dict:
    body = instruction.model_dump(mode='json', exclude_none=True)
    body['numeroAdherente'] = adherente
    if isinstance(instruction, TransferRequest):
        if instruction.fechaPago and instruction.fechaPago != today:
            raise ValueError('La fechaPago de la transferencia debe ser la fecha operativa del banco.')
        if instruction.fechaPago:
            body['fechaPago'] = instruction.fechaPago.strftime('%Y%m%d')
        for i, b in enumerate(body['beneficiarios']):
            b['orden'] = i
    else:
        for i, echeq in enumerate(instruction.echeqs):
            if echeq.tipoCheque == 'ECHC' and echeq.fechaPago != today:
                raise ValueError('Un ECHC debe tener fechaPago igual a la fecha operativa del banco.')
            if echeq.tipoCheque == 'ECHD' and echeq.fechaPago <= today:
                raise ValueError('Un ECHD debe tener fechaPago posterior a la fecha operativa del banco.')
            body['echeqs'][i]['fechaPago'] = echeq.fechaPago.strftime('%Y%m%d')
    # Omitir arrays opcionales vacíos: no simular datos de firmantes ni correos.
    if not body['operadoresFirmantes']:
        del body['operadoresFirmantes']
    for row in body.get('beneficiarios', body.get('echeqs', [])):
        if not row['mails']:
            del row['mails']
    return body


def echeq_management_payload(instruction: EcheqManagementRequest, adherente: int) -> dict:
    body = instruction.model_dump(mode='json', exclude_none=True)
    body['numeroAdherente'] = adherente
    for index, item in enumerate(instruction.echeqs):
        if item.fechaPago is not None:
            body['echeqs'][index]['fechaPago'] = item.fechaPago.strftime('%Y%m%d')
    if not body['operadoresFirmantes']:
        del body['operadoresFirmantes']
    return body


def echeq_list_payload(instruction: EcheqListRequest, adherente: int) -> dict:
    body = instruction.model_dump(mode='json', exclude_none=True)
    body['numeroAdherente'] = adherente
    for key in ('fechaEmisionDesde', 'fechaEmisionHasta', 'fechaPagoDesde', 'fechaPagoHasta'):
        value = body['filtro'].get(key)
        if value:
            body['filtro'][key] = value.replace('-', '')
    return body


def fci_instruction_payload(
    instruction: FciSubscriptionRequest | FciRedemptionRequest,
    adherente: int,
) -> dict:
    body = instruction.model_dump(mode='json', exclude_none=True)
    body['numeroAdherente'] = adherente
    body['operadoresFirmantes'] = [{'documento': FCI_SIGNER_DNI, 'documentoTipo': 'DNI'}]
    if isinstance(instruction, FciRedemptionRequest):
        units = instruction.solicitudRescate.cuotapartes
        if units is not None:
            body['solicitudRescate']['cuotapartes'] = (
                int(units) if units == units.to_integral_value() else float(units)
            )
    return body

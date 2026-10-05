from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='CREDICOOP_', env_parse_none_str='null', extra='ignore')
    base_url: str = 'https://homoapibccl.bancocredicoop.coop'
    realm_url: str = 'https://homoapibccl.bancocredicoop.coop/auth/realms/homologacion'
    client_id: str = '30662210877'
    adherente: int = 661395
    private_key_path: Path = Path('secrets/30662210877-HOMOprivate.pem')
    private_key_password: SecretStr | None = None
    api_key: SecretStr = SecretStr('')
    journal_path: Path = Path('data/operaciones.sqlite3')
    fecha_operativa: date | None = date(2026, 8, 28)
    timeout: float = Field(default=30, gt=0, le=120)
    ca_bundle: Path | None = None
    scopes: str = 'cuentas transferenciasConFirma echeqConFirma fciConFirma beneficiarioTransferencia beneficiarioEcheq consultaCbuCvuAlias'
    drive_folder_id: str = '1xa_14O0TERbR_kPaQhledLGEl0p77m24'
    drive_credentials_path: Path = Path('credentials.json')
    supplier_master_path: Path = Path('Beneficiarios_Credicoop.xlsx')

    @model_validator(mode='after')
    def valid_configuration(self):
        from urllib.parse import urlsplit
        for url in (self.base_url, self.realm_url):
            p = urlsplit(url)
            if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError('Las URLs del banco deben ser HTTPS sin credenciales, query ni fragmento.')
        if urlsplit(self.base_url).netloc != urlsplit(self.realm_url).netloc:
            raise ValueError('La API y el realm deben pertenecer al mismo servidor.')
        if len(self.api_key.get_secret_value()) < 32:
            raise ValueError('Configurar CREDICOOP_API_KEY con una clave local de al menos 32 caracteres.')
        enabled = set(self.scopes.split())
        if not {'cuentas', 'transferenciasConFirma', 'echeqConFirma'} <= enabled:
            raise ValueError('Faltan scopes de cuentas o de operaciones ConFirma.')
        if enabled & {'transferencias', 'echeq', 'fci', 'vep'}:
            raise ValueError('Este proyecto no admite scopes de envío directo.')
        if 'homoapibccl' not in urlsplit(self.base_url).hostname and self.fecha_operativa is not None:
            raise ValueError('Fuera de homologación debe quitarse la fecha operativa fija.')
        return self

    @property
    def is_homologation(self) -> bool:
        from urllib.parse import urlsplit
        return urlsplit(self.base_url).hostname == 'homoapibccl.bancocredicoop.coop'

    @property
    def token_url(self) -> str:
        return self.realm_url.rstrip('/') + '/protocol/openid-connect/token'

    def operational_today(self) -> date:
        return self.fecha_operativa or argentina_today()


def argentina_today() -> date:
    # Argentina usa UTC-3; funciona también en Windows sin base de zonas IANA.
    return datetime.now(timezone(timedelta(hours=-3))).date()

from getpass import getpass
from argon2 import PasswordHasher


def main():
    password = getpass('Nueva contraseña (mínimo 12 caracteres): ')
    confirm = getpass('Repetir contraseña: ')
    if len(password) < 12:
        raise SystemExit('La contraseña debe tener al menos 12 caracteres.')
    if password != confirm:
        raise SystemExit('Las contraseñas no coinciden.')
    print(PasswordHasher().hash(password))


if __name__ == '__main__':
    main()

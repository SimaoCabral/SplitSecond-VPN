# Split/Second VPN

Cliente GUI para ligar jogadores a uma rede tinc VPN e jogar **Split/Second** em modo LAN pela internet.

Usa tinc em modo switch (Layer 2) para encaminhar broadcasts UDP, necessários para a descoberta de jogadores do jogo.

---

## Descarregar

Vai à [página de Releases](../../releases/latest) e descarrega o ficheiro para o teu sistema:

| Sistema | Ficheiro | Como executar |
|---------|----------|---------------|
| Linux x86-64 | `splitsecond-vpn` | `chmod +x splitsecond-vpn && ./splitsecond-vpn` |
| Windows 10/11 | `splitsecond-vpn.exe` | Duplo-clique → aceitar UAC |

Os binários são standalone — não precisam de instalar Python, tinc, nem nenhuma dependência. O programa instala o tinc automaticamente no primeiro passo.

Para instruções completas de configuração, ver [GUIAO.md](GUIAO.md).

---

## Compilar a partir do código fonte

### Linux

```bash
git clone https://github.com/SimaoCabral/SplitSecond-VPN.git
cd SplitSecond-VPN
bash build.sh
# binário em dist/splitsecond-vpn
```

Requer: Python 3.9+ e `tk` instalado (`sudo pacman -S tk` / `sudo apt install python3-tk`).

### Windows

```bat
git clone https://github.com/SimaoCabral/SplitSecond-VPN.git
cd SplitSecond-VPN
build.bat
:: executável em dist\splitsecond-vpn.exe
```

Requer: Python 3.9+ instalado e no PATH.

### O que os scripts de build fazem

1. Criam um ambiente virtual Python (`.venv`)
2. Instalam `customtkinter` e `pyinstaller`
3. Compilam com PyInstaller `--onefile --windowed`
   - No Windows: inclui `--uac-admin` para elevar automaticamente
4. Resultado: binário standalone em `dist/`

---

## CI/CD — Builds automáticos

As releases são criadas automaticamente via GitHub Actions quando é feito push de uma tag `v*`:

```bash
git tag v1.0.0
git push origin v1.0.0
```

O workflow (`.github/workflows/build.yml`) compila em paralelo para Linux (`ubuntu-latest`) e Windows (`windows-latest`) e publica os dois binários na release.

---

## Estrutura do projecto

```
splitsecond-vpn/
├── splitsecond_vpn.py      # programa principal
├── build.sh                # compilar no Linux
├── build.bat               # compilar no Windows
├── requirements.txt        # dependências Python
├── GUIAO.md                # guião de instalação para jogadores
└── .github/workflows/
    └── build.yml           # CI/CD: build + release automáticos
```

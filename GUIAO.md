# Split/Second VPN — Guião de Instalação

> Liga-te a outros jogadores para jogar Split/Second em modo multijogador pela internet, como se estivessem na mesma rede local.

---

## Índice

1. [Jogadores — Windows](#1-jogadores--windows)
2. [Jogadores — Linux](#2-jogadores--linux)
3. [Troca de ficheiros com o organizador](#3-troca-de-ficheiros-com-o-organizador)
4. [Resolver problemas comuns](#4-resolver-problemas-comuns)
5. [Para o organizador — configurar o servidor](#5-para-o-organizador--configurar-o-servidor)

---

## 1. Jogadores — Windows

### O que vais precisar

- O ficheiro **`splitsecond-vpn.exe`** (o organizador partilha o link para descarregar)
- O conteúdo do ficheiro **`hosts/server`** (o organizador envia-te por Discord, WhatsApp, etc.)
- Um **número de IP** atribuído pelo organizador (por exemplo: `2`, `3`, `4`…)

---

### Passo 1 — Descarregar e abrir o programa

1. Descarrega o ficheiro `splitsecond-vpn.exe` a partir do link que o organizador partilhou.
2. Faz **duplo-clique** no ficheiro.
3. Aparece uma janela do Windows a perguntar se permites que o programa faça alterações — clica **Sim**. Isto é necessário porque o programa precisa de instalar software de rede.

O programa abre e mostra o **Passo 1 de 6**.

---

### Passo 2 — Instalar o tinc (software de VPN)

O programa mostra o **Passo 1 — Instalar tinc**.

1. Clica no botão **"Instalar automaticamente"**.
2. Aguarda — o programa descarrega e instala tudo sozinho (pode demorar 1-2 minutos).
3. Quando aparecer a mensagem **"tinc encontrado"** a verde, o passo está concluído.
4. Clica **Seguinte →**.

---

### Passo 3 — Instalar o driver TAP

O programa mostra o **Passo 2 — Driver TAP**.

Este passo instala um adaptador de rede virtual que o tinc precisa para funcionar.

1. Clica **"Instalar driver TAP"**.
2. Aguarda a mensagem **"Adaptador 'tap0901' encontrado"** a verde.
3. Clica **Seguinte →**.

---

### Passo 4 — Configurar o teu jogador

O programa mostra o **Passo 3 — Configurar jogador**.

1. No campo **"Nome do jogador"**, escreve o teu nome (sem espaços, por exemplo: `Simao` ou `Jogador1`).
2. No campo **"10.20.0. ___"**, escreve o número que o organizador te atribuiu (por exemplo: `2`).
3. Clica **"Criar ficheiros + gerar chaves"**.
4. Aguarda as mensagens **"Ficheiros criados"** e **"Chaves geradas"** no painel de log em baixo.
5. Clica **Seguinte →**.

---

### Passo 5 — Colocar o ficheiro do servidor

O programa mostra o **Passo 4 — Ficheiro do servidor**.

O organizador vai enviar-te um bloco de texto (é a chave de identificação do servidor). Precisas de o colar aqui.

1. Copia todo o texto que o organizador te enviou (selecciona tudo e prime **Ctrl+C**).
2. Clica dentro da caixa grande em branco no programa.
3. Prime **Ctrl+V** para colar.
4. Clica **"Aplicar ficheiro do servidor"**.
5. No campo **"IP público do servidor"**, escreve o IP que o organizador indicou (por exemplo: `85.243.12.34`).
6. Clica **"Aplicar IP"**.
7. Clica **Seguinte →**.

---

### Passo 6 — Enviar o teu ficheiro ao organizador

O programa mostra o **Passo 5 — Enviar host file**.

Agora és tu a enviar informação ao organizador, para ele poder aceitar-te na rede.

1. Clica **"Copiar"** — o texto da caixa é copiado automaticamente para a área de transferência.
2. Cola esse texto numa mensagem para o organizador (Discord, WhatsApp, etc.) e envia.
3. **Aguarda** que o organizador confirme que recebeu e adicionou o teu ficheiro.
4. Quando o organizador confirmar, assinala a caixa **"Já enviei ao organizador e recebi confirmação"**.
5. Clica **Seguinte →**.

---

### Passo 7 — Ligar e jogar

O programa mostra o **Passo 6 — Ligar à VPN**.

1. Clica **"LIGAR"**.
2. Aguarda que o **ping ao servidor** mostre **"OK ✓"** — isto confirma que estás ligado.
3. Abre o Split/Second e vai ao modo **Multijogador / LAN**.

> **Tens Radmin VPN instalado?** Se sim, antes de abrir o jogo vai às Ligações de Rede (clica no ícone de rede na barra de tarefas → "Definições de rede e internet" → "Definições avançadas de rede") e desactiva o adaptador do Radmin. Podes reactivá-lo depois de jogar.

---

## 2. Jogadores — Linux

### O que vais precisar

- O ficheiro **`splitsecond-vpn`** (o organizador partilha o link para descarregar)
- O conteúdo do ficheiro **`hosts/server`** (o organizador envia por Discord, WhatsApp, etc.)
- Um **número de IP** atribuído pelo organizador (por exemplo: `2`, `3`, `4`…)

---

### Passo 1 — Descarregar e preparar o programa

1. Descarrega o ficheiro `splitsecond-vpn` a partir do link que o organizador partilhou.
2. Abre a pasta onde ficou guardado (normalmente a pasta **Transferências**).
3. Clica com o botão **direito** no ficheiro → **Propriedades** → separador **Permissões** → activa a opção **"Permitir executar o ficheiro como programa"** (ou similar, depende do ambiente de trabalho).
   - Em alternativa, se estiveres confortável com um terminal: `chmod +x splitsecond-vpn`
4. Faz **duplo-clique** no ficheiro para o abrir (ou clica com o botão direito → **Executar**).

> Quando o programa pedir autorização (janela de password), introduz a tua password de utilizador. É necessário para instalar o tinc e configurar a rede.

O programa abre e mostra o **Passo 1**.

---

### Passos seguintes

Os passos no Linux são iguais ao Windows, **excepto**:

- **Não existe Passo 2 (Driver TAP)** — no Linux não é necessário.
- **Passo 1 — Instalar tinc**: clica **"Instalar automaticamente"**. O programa detecta a tua distribuição e instala com o gestor de pacotes correcto.
  - **Bazzite**: o programa avisará que tens de instalar manualmente e reiniciar o computador antes de continuar.
- Os restantes passos (configurar jogador, ficheiro do servidor, enviar host file, ligar) são iguais ao Windows — segue os passos 4 a 7 da secção Windows acima.

---

## 3. Troca de ficheiros com o organizador

Este é o único passo que requer comunicação entre ti e o organizador. É feito **uma única vez** por jogador (ou quando alguém entra de novo no grupo).

```
O que acontece:

  TU  ──────► envias o teu "host file" ──────► ORGANIZADOR
                                                    │
                                                    │ (adiciona ao servidor)
                                                    │
  TU  ◄────── recebes o "hosts/server" ◄──────────-┘
```

**Porquê?** O servidor precisa de saber quem és (a tua chave de identificação) para te deixar entrar. E tu precisas de saber onde está o servidor (o endereço e a chave dele).

**O que envias** → um bloco de texto que aparece no **Passo 5** do programa (clica "Copiar" e cola numa mensagem).

**O que recebes** → outro bloco de texto que o organizador te envia e que colas no **Passo 4** do programa.

**Estes textos não são dados pessoais** — são apenas chaves de identificação criptográfica, como um crachá de acesso.

---

## 4. Resolver problemas comuns

### O programa não abre / pede para elevar

- **Windows**: é normal aparecer uma janela a pedir permissão — clica **Sim**. O programa precisa de permissões de administrador para instalar drivers de rede.

### "tinc não arrancou" ou não consigo ligar

1. Verifica se todos os passos anteriores têm o indicador ✓ verde na barra lateral.
2. Confirma com o organizador que ele adicionou o teu ficheiro e **reiniciou o servidor**.
3. Confirma que o IP público no Passo 4 está correcto.

### O ping ao servidor diz "sem resposta"

- Aguarda 10-15 segundos após clicar LIGAR antes de testar.
- Confirma com o organizador que o servidor tinc está a correr (`sudo systemctl status tinc@splitsecond`).

### O jogo não encontra outros jogadores (Windows)

- Desactiva temporariamente o adaptador **Radmin VPN** nas Ligações de Rede (se o tiveres instalado).
- Confirma com `ipconfig` (na Linha de Comandos) que o endereço `10.20.0.X` aparece listado.

### O jogo não encontra outros jogadores (Linux / Proton)

O Split/Second no Linux pode ligar-se à interface de rede errada. Esta situação é mais técnica — consulta a documentação sobre **network namespaces** para isolar o jogo na interface VPN.

### O IP do servidor mudou

O organizador comunica o novo IP. No programa, vai ao **Passo 4**, introduz o novo IP no campo "IP público do servidor" e clica **"Aplicar IP"**.

---

## 5. Para o organizador — configurar o servidor

> Esta secção é técnica e destina-se a quem configura o Raspberry Pi. Os jogadores não precisam de ler isto.

### 5.1 Instalar tinc

```bash
sudo apt update && sudo apt install tinc -y
```

### 5.2 Criar estrutura de directórios

```bash
sudo mkdir -p /etc/tinc/splitsecond/hosts
```

### 5.3 Ficheiro de configuração principal

```bash
sudo nano /etc/tinc/splitsecond/tinc.conf
```

```
Name = server
Mode = switch
Port = 11655
```

### 5.4 Ficheiro de host do servidor

```bash
sudo nano /etc/tinc/splitsecond/hosts/server
```

```
Address = <IP_PUBLICO>
Port = 11655
Subnet = 10.20.0.1/32
```

> **IP dinâmico?** Considera um serviço de DNS dinâmico como [DuckDNS](https://www.duckdns.org) e coloca o hostname no campo `Address`. Os jogadores podem usar o hostname em vez do IP.

### 5.5 Gerar chaves do servidor

```bash
sudo tincd -n splitsecond --generate-keys
```

### 5.6 Scripts de rede

`/etc/tinc/splitsecond/tinc-up`:
```bash
#!/bin/bash
ip link set $INTERFACE up
ip addr add 10.20.0.1/24 dev $INTERFACE
```

`/etc/tinc/splitsecond/tinc-down`:
```bash
#!/bin/bash
ip addr del 10.20.0.1/24 dev $INTERFACE || true
ip link set $INTERFACE down || true
```

```bash
sudo chmod +x /etc/tinc/splitsecond/tinc-up
sudo chmod +x /etc/tinc/splitsecond/tinc-down
```

### 5.7 Firewall e arranque

```bash
sudo ufw allow 11655/tcp
sudo ufw allow 11655/udp
sudo systemctl enable tinc@splitsecond
sudo systemctl start  tinc@splitsecond
```

### 5.8 Aceitar um novo jogador

Quando um jogador enviar o seu host file:

```bash
sudo nano /etc/tinc/splitsecond/hosts/<NOME_DO_JOGADOR>
# colar o conteúdo enviado pelo jogador
sudo systemctl restart tinc@splitsecond
```

Depois envia ao jogador o conteúdo de:

```bash
cat /etc/tinc/splitsecond/hosts/server
```

### 5.9 IPs atribuídos

| Jogador | IP VPN |
|---------|--------|
| Servidor | 10.20.0.1 |
| Jogador 1 | 10.20.0.2 |
| Jogador 2 | 10.20.0.3 |
| Jogador 3 | 10.20.0.4 |
| … | … |

Máscara: `255.255.255.0` · Porta: `11655` TCP + UDP

# Karaoke System

Um sistema de Karaokê simples e divertido feito em Python. Baixa músicas do YouTube Music, exibe letras sincronizadas e pontua sua performance baseada no ritmo.

## Funcionalidades

*   **Interface Gráfica (GUI):** Gerencie suas músicas com uma interface visual moderna.
*   **Busca e Preview:** Busque músicas no YouTube Music e assista ao vídeo dentro do app antes de baixar.
*   **Download em Massa:** Cole uma lista de links para baixar várias músicas de uma vez. (testes pendentes)
*   **Download Automático:** Baixa o áudio (MP3) e a letra sincronizada.
*   **Inteligência Artificial (IA):**
    *   **Demucs:** Separação automática de voz e instrumental (playback) de alta qualidade.
    *   **Whisper:** Transcrição automática de legendas com timestamps precisos.
    *   **Sincronia:** Usa IA para corrigir legendas baseando-se nas letras oficiais.
*   **Fila de Reprodução:** Digite o código de novas músicas para adicioná-las à fila enquanto outra toca.
*   **Pontuação de Ritmo:** O sistema "ouve" você cantar (via microfone) e dá uma nota de 0 a 100.
*   **Visualização:** Letras exibidas em estilo "página" (duas linhas por vez) para facilitar a leitura.
*   **Controle de Áudio:** Alterne entre a versão Original e Instrumental a qualquer momento.

## Pré-requisitos

Você precisa ter o **FFmpeg** instalado no seu sistema.

*   **Ubuntu/Debian:** `sudo apt install ffmpeg portaudio19-dev`
*   **Windows:** Baixe e instale o FFmpeg e adicione ao PATH.

## Instalação

1.  Clone o repositório.
2.  Instale as dependências Python para o script correspondente:

```bash
pip install -r requirements_song_manager.txt
```

```bash
pip install -r requirements_karaoke_player.txt
```

## Como Usar

### 1. Adicionar Músicas

Antes de cantar, você precisa construir sua biblioteca de músicas. Execute o gerenciador:

```bash
python song_manager.py
```

O gerenciador agora possui uma interface gráfica.
1.  Use a aba **Search** para buscar músicas.
2.  Clique em um resultado para ver o **preview do vídeo** (player do YouTube incorporado).
3.  Clique em **Download Selected** para baixar.
4.  O sistema processará a música com IA (Whisper + Demucs) para gerar legendas e instrumental.
5.  O sistema gerará um **Código Numérico** para cada música. Anote-os!

### 2. Cantar (O Player)

Inicie o sistema de Karaokê:

```bash
python karaoke_player.py
```

1.  Na tela de menu, você verá a lista de músicas disponíveis e seus códigos.
2.  Digite o código da música e pressione **ENTER**.
3.  A música irá para a fila e começar a tocar.
4.  **Enquanto canta:** Você pode digitar o código de outra música e dar ENTER para adicioná-la à fila.
5.  Ao final, veja sua pontuação!

## Controles

*   **Teclado Numérico + Enter:** Digitar código e confirmar para fila.
*   **Tecla 'V':** Alternar entre Áudio **Instrumental** (Padrão) e **Vocal** (Original).
*   **Backspace:** Corrigir digitação.

## Resolução de Problemas

*   **Erro de Download (403 Forbidden):** O YouTube às vezes bloqueia downloads automatizados. O sistema tentará métodos alternativos.
*   **Microfone:** Certifique-se de que seu microfone padrão está configurado corretamente no sistema operacional.
*   **Letras não aparecem:** Verifique se o processamento da música (song_manager) foi concluído sem erros.

## Sobre o Projeto

Este projeto foi desenvolvido para uso pessoal e tem como objetivo principal o estudo e teste de diversas tecnologias. Colaborações são sempre bem-vindas!

## Créditos

*   **Idealização e Desenvolvimento:** Luciano Silva

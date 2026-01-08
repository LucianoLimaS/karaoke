import pygame
import sys
import os
import re
import time
import random
import threading
import json
from scorer import Scorer

# Constantes
WIDTH, HEIGHT = 1024, 768
FPS = 60
FONT_SIZE_LYRICS = 40
FONT_SIZE_INFO = 24
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_HIGHLIGHT = (255, 215, 0)  # Dourado
COLOR_BG_OVERLAY = (0, 0, 0, 150) # Overlay escuro para legibilidade


class SongLibrary:
    """
    Classe simples para carregar a biblioteca de músicas do arquivo JSON.
    """
    def __init__(self, library_file="library.json"):
        self.library_file = library_file
        self.library = {}
        self.load_library()

    def load_library(self):
        """Carrega o arquivo library.json para a memória."""
        try:
            with open(self.library_file, 'r', encoding='utf-8') as f:
                self.library = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.library = {}

class KaraokePlayer:
    """
    Classe principal do Player de Karaokê usando Pygame.
    Gerencia a interface, reprodução de áudio, letras e pontuação.
    """
    def __init__(self):
        pygame.init()
        pygame.mixer.init()

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Python Karaoke System")
        self.clock = pygame.time.Clock()

        self.manager = SongLibrary()
        self.scorer = Scorer()

        self.font_lyrics = pygame.font.Font(None, FONT_SIZE_LYRICS)
        self.font_info = pygame.font.Font(None, FONT_SIZE_INFO)

        self.current_song = None
        self.lyrics = [] # Lista de (timestamp_ms, text)
        self.current_line_index = -1

        self.queue = []
        self.input_buffer = ""

        self.state = "MENU" # MENU, PLAYING, SCORE
        self.background = None
        self.load_random_background()

        self.score_result = 0

    def load_random_background(self):
        """
        Gera um fundo gradiente aleatório para cada música.
        Isso cria uma estética visual dinâmica.
        """
        # Em um cenário real, poderíamos baixar imagens.
        # Aqui criamos uma superfície de gradiente.
        self.background = pygame.Surface((WIDTH, HEIGHT))

        # Cria um gradiente
        c1 = (random.randint(0,100), random.randint(0,100), random.randint(50,150))
        c2 = (random.randint(0,50), random.randint(0,50), random.randint(100,200))

        for y in range(HEIGHT):
            r = c1[0] + (c2[0] - c1[0]) * y // HEIGHT
            g = c1[1] + (c2[1] - c1[1]) * y // HEIGHT
            b = c1[2] + (c2[2] - c1[2]) * y // HEIGHT
            pygame.draw.line(self.background, (r,g,b), (0,y), (WIDTH,y))

    def parse_lrc(self, lrc_path):
        """
        Analisa o arquivo de letras. Suporta tanto o formato padrão .lrc
        quanto o formato JSON aprimorado com tempos exatos por palavra.
        """
        # Suporte a JSON para nível de palavra (word-level)
        if lrc_path.endswith('.json'):
            import json
            try:
                with open(lrc_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Retorna a lista de linhas diretamente, formato esperado:
                    # [{'start': s, 'end': e, 'text': t, 'words': [...]}, ...]
                    # Converte start/end para milissegundos
                    lines = []
                    for l in data.get('lines', []):
                         l['time'] = l['start'] * 1000
                         l['end_time'] = l['end'] * 1000
                         # Processar palavras
                         for w in l.get('words', []):
                             w['start_ms'] = w['start'] * 1000
                             w['end_ms'] = w['end'] * 1000
                         lines.append(l)
                    return lines
            except Exception as e:
                print(f"Erro ao analisar letras JSON: {e}")
                return []

        lyrics = []
        if not lrc_path or not os.path.exists(lrc_path):
            return []

        with open(lrc_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Regex para extrair timestamp [mm:ss.xx]
                match = re.search(r'\[(\d+):(\d+\.\d+)\](.*)', line)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    text = match.group(3).strip()
                    time_ms = (minutes * 60 + seconds) * 1000
                    lyrics.append({'time': time_ms, 'text': text})
        return lyrics

    def start_song(self, song_id):
        """
        Inicia a reprodução de uma música pelo ID:
        1. Carrega dados da música.
        2. Tenta carregar letras (JSON ou LRC).
        3. Carrega o áudio no mixer do Pygame.
        4. Reinicia o pontuador (Scorer).
        """
        song_data = self.manager.library.get(song_id)
        if not song_data:
            print(f"Música {song_id} não encontrada!")
            return
            
        print(f"Iniciando música: {song_data['title']}")

        self.current_song = song_data
        
        # Verifica se há path JSON ou fallback para LRC
        lyric_path = song_data.get('lrc_path')
        # Podemos ter salvo um path json em "lrc_path" se atualizamos o manager corretamente,
        # OU podemos precisar deduzir.
        # Verifica versao JSON se path for .lrc
        if lyric_path and lyric_path.endswith('.lrc'):
            json_path = lyric_path.replace('.lrc', '_lyrics.json')
            if os.path.exists(json_path):
                lyric_path = json_path
        
        self.lyrics = self.parse_lrc(lyric_path)

        # Carrega Áudio
        try:
            pygame.mixer.music.load(song_data['audio_path'])
            pygame.mixer.music.play()
        except pygame.error as e:
            print(f"Não foi possível carregar o áudio: {e}")
            return
        
        self.state = "PLAYING"
        self.scorer.reset()
        self.scorer.start()
        self.load_random_background()
        
    def get_current_time(self):
        """
        Retorna o tempo de reprodução atual em milissegundos.
        Compensa o offset caso tenhamos alternado faixas de áudio no meio da música.
        """
        # pygame.mixer.music.get_pos() retorna tempo desde o último play().
        # Devemos somar o offset (de onde começamos a tocar).
        if not hasattr(self, 'current_offset_ms'):
             self.current_offset_ms = 0
             
        # get_pos retorna -1 se não estiver tocando
        pos = pygame.mixer.music.get_pos()
        if pos == -1: return 0
        
        return pos + self.current_offset_ms

    def toggle_audio_track(self):
        """
        Alterna entre a faixa instrumental e a original (com vocal) se disponível.
        Mantém a sincronia calculando o tempo exato para retomar.
        MELHORIA: Reproduzir as 2 faixas juntas, pois a troca do arquivo de áudio
        pode causar um pequeno desalinhamento.
        """
        if not self.current_song: return
        
        if not hasattr(self, 'current_track_type'):
            self.current_track_type = 'instrumental'
        
        # Determina caminhos dos arquivos
        inst_path = self.current_song.get('audio_path') 
        orig_path = self.current_song.get('original_audio_path')
        
        # Calcula posição atual para retomar
        current_time_ms = self.get_current_time()
        start_sec = current_time_ms / 1000.0
        
        try:
            target_file = None
            target_type = None
            
            if self.current_track_type == 'instrumental':
                # Trocar para a versão com vocal
                if orig_path and os.path.exists(orig_path):
                    target_file = orig_path
                    target_type = 'vocal'
            else:
                # Trocar para a versão instrumental
                if inst_path and os.path.exists(inst_path):
                    target_file = inst_path
                    target_type = 'instrumental'
            
            if target_file:
                pygame.mixer.music.load(target_file)
                pygame.mixer.music.play(start=start_sec)
                
                # IMPORTANTE: Resetar offset! 
                # Por que? get_pos vai resetar para 0.
                # Então tempo total = 0 (pos) + start_sec * 1000 (offset)
                self.current_offset_ms = int(start_sec * 1000)
                
                self.current_track_type = target_type
                # print(f"Alternado para {target_type}") # Check de Debug
            
        except Exception as e:
            print(f"Erro ao alternar áudio: {e}")

    def handle_input(self, event):
        """
        Gerencia os eventos de entrada do usuário (teclado).
        - ENTER: Adiciona música à fila se houver código digitado.
        - V: Alterna entre faixa vocal e instrumental.
        - Números/Backspace: Digitação do código da música.
        """
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                if self.input_buffer:
                    if self.input_buffer in self.manager.library:
                        self.queue.append(self.input_buffer)
                        print(f"Adicionado {self.input_buffer} à fila.")
                    else:
                        print("Código inválido.")
                    self.input_buffer = ""
                elif self.state == "SCORE":
                     self.state = "MENU"
            
            elif event.key == pygame.K_v:
                self.toggle_audio_track()
                
            elif event.key == pygame.K_BACKSPACE:
                self.input_buffer = self.input_buffer[:-1]
            elif event.unicode.isnumeric():
                self.input_buffer += event.unicode

    def update(self):
        """
        Loop principal de lógica.
        - Atualiza a linha atual da letra baseada no tempo.
        - Gerencia a paginação das letras (exibir par de linhas).
        - Alimenta o Scorer com informação se o usuário deveria estar cantando.
        """
        if self.state == "PLAYING":
            if not pygame.mixer.music.get_busy():
                self.finish_song()
                return
            
            # Usa getter de tempo fixo
            current_time = self.get_current_time()
            
            # Encontra a linha atual (busca linear simples)
            found_index = -1
            for i, line in enumerate(self.lyrics):
                if current_time >= line['time'] - 200:
                     found_index = i
                else:
                    break
            
            if not hasattr(self, 'page_index'): self.page_index = 0
            

            # Atualiza índice da PÁGINA
            # Lógica de Paginação de Letras:
            # O player exibe 2 linhas por vez. Precisamos decidir quando virar a "página" (avançar 2 linhas).
            # A condição verifica se o tempo atual já passou do final da segunda linha do par (linha de baixo).
            # Se for a última linha (ímpar), verifica o final dela mesma.
            if self.page_index + 1 < len(self.lyrics):
                # Caso comum: Par de linhas
                line_end = self.lyrics[self.page_index + 1].get('end_time', self.lyrics[self.page_index + 1]['time'] + 5000)
                if current_time > line_end:
                    self.page_index += 2
                    
            elif self.page_index < len(self.lyrics):
                 # Última linha (caso ímpar)
                 line_end = self.lyrics[self.page_index].get('end_time', self.lyrics[self.page_index]['time'] + 5000)
                 if current_time > line_end:
                     self.page_index += 2

            self.current_line_index = found_index
            
            # Lógica de Pontuação:
            # Verifica se o índice da linha atual é válido.
            # Se o tempo atual estiver dentro do intervalo de tempo da linha (start < now < end),
            # consideramos que é um "segmento de canto".
            # O Scorer será notificado (set_singing_segment(True)) e começará a analisar o microfone
            # para ver se há entrada de áudio (volume/ritmo) correspondente.
            # Caso contrário, o Scorer pausa a análise de pontuação.
            if 0 <= self.current_line_index < len(self.lyrics):
                l = self.lyrics[self.current_line_index]
                end_time = l.get('end_time', l['time'] + 5000)
                if l['time'] <= current_time <= end_time:
                    self.scorer.set_singing_segment(True)
                else:
                    self.scorer.set_singing_segment(False)
            else:
                 self.scorer.set_singing_segment(False)

        elif self.state == "MENU":
            if self.queue:
                next_song = self.queue.pop(0)
                self.start_song(next_song)
                self.page_index = 0 
                self.current_track_type = 'instrumental'
                self.current_offset_ms = 0 # Reseta o offset para a nova música

    def finish_song(self):
        """
        Chamado quando a música termina.
        Para o pontuador, calcula a nota final e muda o estado para SCORE.
        """
        self.scorer.stop()
        self.score_result = self.scorer.get_score()
        self.state = "SCORE"

    def draw(self):
        """
        Método principal de renderização.
        Desenha o fundo, overlay, e a interface apropriada para o estado atual (MENU, PLAYING, SCORE).
        """
        # Desenhar Fundo
        self.screen.blit(self.background, (0,0))

        # Desenhar Camada Escura (Overlay)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill(COLOR_BG_OVERLAY)
        self.screen.blit(overlay, (0,0))

        if self.state == "MENU":
            self.draw_centered_text("SISTEMA DE KARAOKÊ", -100, 60)
            self.draw_centered_text("Digite o código e pressione ENTER para adicionar à fila", -50)
            self.draw_centered_text(f"Fila: {', '.join(self.queue)}", 50)

            # Mostrar Biblioteca
            y_offset = 150
            for code, data in list(self.manager.library.items())[:10]:
                text = f"[{code}] {data['title']} - {data['artist']}"
                surf = self.font_info.render(text, True, COLOR_WHITE)
                self.screen.blit(surf, (50, y_offset))
                y_offset += 30

            # Box de Entrada
            input_surf = self.font_info.render(f"Entrada: {self.input_buffer}", True, COLOR_HIGHLIGHT)
            self.screen.blit(input_surf, (50, HEIGHT - 50))

        elif self.state == "PLAYING":
            # Desenha Informações da Música
            # Traduz tipo de faixa
            t_type = getattr(self, 'current_track_type', 'instrumental')
            type_label = "INSTRUMENTAL" if t_type == 'instrumental' else "VOCAL"
            
            info_text = f"{self.current_song['title']} - {self.current_song['artist']} ({type_label}) ['V' para Alternar]"
            surf = self.font_info.render(info_text, True, COLOR_HIGHLIGHT)
            self.screen.blit(surf, (20, 20))

            # Desenha Letras - PAGINADO
            # Usa helper
            current_time = self.get_current_time()
            
            if hasattr(self, 'page_index') and self.page_index < len(self.lyrics):
                line_data = self.lyrics[self.page_index]
                if 'words' in line_data:
                    self.draw_karaoke_line(line_data, current_time, y_offset=-40) 
                else:
                    self.draw_centered_text(line_data['text'], -40, 50, COLOR_HIGHLIGHT)

            if hasattr(self, 'page_index') and self.page_index + 1 < len(self.lyrics):
                line_data = self.lyrics[self.page_index + 1]
                if 'words' in line_data:
                    self.draw_karaoke_line(line_data, current_time, y_offset=40) 
                else:
                    self.draw_centered_text(line_data['text'], 40, 30, (200,200,200)) 

            # Desenha Input da Fila
            if self.input_buffer:
                input_surf = self.font_info.render(f"Adicionando: {self.input_buffer}", True, COLOR_WHITE)
                self.screen.blit(input_surf, (20, HEIGHT - 40))

        elif self.state == "SCORE":
            self.draw_centered_text("MÚSICA FINALIZADA", -50)
            self.draw_centered_text(f"Sua Pontuação: {self.score_result}/100", 20, 80, COLOR_HIGHLIGHT)
            self.draw_centered_text("Pressione ENTER para continuar", 100, 30)

        pygame.display.flip()
    
    def draw_karaoke_line(self, line_data, current_time, y_offset=0):
        """
        Renderiza uma linha de palavras, colorindo-as 'estilo karaokê' baseado no timing.
        """
        words = line_data.get('words', [])
        total_width = 0
        surfaces = []
        
        # Primeiro passo: Calcular largura total
        # Iteramos sobre todas as palavras para renderizá-las (mesmo que temporariamente) e somar suas larguras.
        # Isso é necessário para saber onde começar a desenhar (start_x) de forma centralizada.
        space_width = self.font_lyrics.size(" ")[0]
        
        for w in words:
            txt = w['display']
            w_start = w['start_ms']
            w_end = w['end_ms']
            
            # Lógica de Cores por Palavra
            # Destaca a sílaba/palavra exata que deve ser cantada no momento.
            if current_time >= w_end:
                 color = COLOR_HIGHLIGHT # Já cantado
            elif current_time >= w_start:
                 color = (255, 100, 100) # Atual (Cantando agora)
            else:
                 color = (200, 200, 200) # Futuro (Ainda não chegou)
            
            s = self.font_lyrics.render(txt, True, color)
            surfaces.append(s)
            total_width += s.get_width() + space_width
            
        # Desenhar centralizado
        start_x = (WIDTH - total_width) // 2
        y = (HEIGHT // 2) + y_offset
        
        current_x = start_x
        for s in surfaces:
            self.screen.blit(s, (current_x, y))
            current_x += s.get_width() + space_width

    def draw_centered_text(self, text, y_offset=0, size=None, color=COLOR_WHITE):
        """
        Função auxiliar para desenhar texto centralizado na tela.
        """
        font = self.font_lyrics
        surface = font.render(text, True, color)
        rect = surface.get_rect(center=(WIDTH // 2, HEIGHT // 2 + y_offset))
        self.screen.blit(surface, rect)

    def run(self):
        """
        Loop principal da aplicação (Game Loop).
        Gerencia eventos, atualizações de lógica e renderização a 60 FPS.
        """
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                self.handle_input(event)

            self.update()
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    app = KaraokePlayer()
    app.run()

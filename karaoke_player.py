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
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (255, 0, 0)
COLOR_BLUE = (0, 100, 255)

class SongLibrary:
    """
    Classe para carregar a biblioteca de músicas do arquivo JSON.
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
        # Inicializa mixer com configurações padrão explícitas para evitar conflitos com PyAudio
        # 44.1kHz, 16-bit signed, Stereo, Buffer 2048
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        except pygame.error:
            print("Aviso: Falha ao inicializar mixer com config padrão. Tentando automático.")
            pygame.mixer.init()

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Sistema de Karaokê Python")
        self.clock = pygame.time.Clock()

        self.manager = SongLibrary()
        self.scorer = Scorer()
        
        # Fontes do Sistema
        self.font_lyrics = pygame.font.Font(None, FONT_SIZE_LYRICS)
        self.font_info = pygame.font.Font(None, FONT_SIZE_INFO)
        self.font_small = pygame.font.Font(None, 20)

        self.current_song = None
        self.lyrics = [] # Lista de (timestamp_ms, text)
        self.current_line_index = -1

        self.queue = []
        self.input_buffer = ""

        self.state = "MENU" # MENU, PLAYING, SCORE, CONFIG
        self.background = None
        self.load_random_background()

        self.score_result = 0
        
        # --- Configurações de Estado ---
        # Padrões
        self.cfg_mic1_idx = None
        self.cfg_mic2_idx = None
        self.cfg_volume_mic1 = 1.0
        self.cfg_volume_mic2 = 1.0
        self.cfg_volume_music = 0.5
        self.cfg_monitoring = False
        self.cfg_latency_chunk = 2048 # Aumentado para 2048 para evitar crashes em monitoramento
        self.cfg_difficulty = "Normal" # Fácil, Normal, Difícil
        self.show_rhythm_indicator = True # Config Visual
        
        # Audio Engine
        self.scorer = Scorer(chunk=self.cfg_latency_chunk)
        self.available_devices = self.scorer.get_input_devices()
        
        # Define device padrao se houver
        if self.available_devices:
            self.cfg_mic1_idx = self.available_devices[0]['index']
            
        self.apply_audio_config()
        self.scorer.start() # Inicia loop de audio (mudo se sem input)

    def load_random_background(self):
        """
        Gera um fundo gradiente aleatório para cada música.
        """
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
        Analisa o arquivo de letras (LRC ou JSON).
        """
        if lrc_path.endswith('.json'):
            import json
            try:
                with open(lrc_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    lines = []
                    for l in data.get('lines', []):
                         l['time'] = l['start'] * 1000
                         l['end_time'] = l['end'] * 1000
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
                match = re.search(r'\[(\d+):(\d+\.\d+)\](.*)', line)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    text = match.group(3).strip()
                    time_ms = (minutes * 60 + seconds) * 1000
                    lyrics.append({'time': time_ms, 'text': text})
        return lyrics

    def start_song(self, song_id):
        """Inicia a reprodução."""
        song_data = self.manager.library.get(song_id)
        if not song_data:
            print(f"Música {song_id} não encontrada!")
            return
            
        print(f"Iniciando música: {song_data['title']}")
        self.current_song = song_data
        
        lyric_path = song_data.get('lrc_path')
        if lyric_path and lyric_path.endswith('.lrc'):
            json_path = lyric_path.replace('.lrc', '_lyrics.json')
            if os.path.exists(json_path):
                lyric_path = json_path
        
        self.lyrics = self.parse_lrc(lyric_path)

        try:
            try:
                # Carrega duração total (necessita recarregar como Sound)
                s = pygame.mixer.Sound(song_data['audio_path'])
                self.total_duration = s.get_length() * 1000
            except:
                self.total_duration = 0

            pygame.mixer.music.load(song_data['audio_path'])
            pygame.mixer.music.set_volume(self.cfg_volume_music)
            pygame.mixer.music.play()
        except pygame.error as e:
            print(f"Não foi possível carregar o áudio: {e}")
            return
        
        self.state = "PLAYING"
        self.scorer.set_paused(False) # Resume audio processing safely
        self.scorer.reset()
        self.load_random_background()
        
    def get_current_time(self):
        """Retorna tempo atual em ms com compensação de offset."""
        if not hasattr(self, 'current_offset_ms'):
             self.current_offset_ms = 0
        pos = pygame.mixer.music.get_pos()
        if pos == -1: return 0
        return pos + self.current_offset_ms
        
    def seek_song(self, delta_sec):
        """Avança ou retrocede a música."""
        if not self.current_song: return
        
        curr_sec = self.get_current_time() / 1000.0
        new_pos = max(0, curr_sec + delta_sec)
        
        # Limita ao final
        if self.total_duration > 0:
             max_sec = self.total_duration / 1000.0
             if new_pos >= max_sec: new_pos = max_sec - 1
        
        try:
             pygame.mixer.music.play(start=new_pos)
             self.current_offset_ms = int(new_pos * 1000)
             
             # Re-sincroniza a página de letras (Aproximação simples)
             # Reseta para buscar do inicio
             self.page_index = 0
             # Avança paginação até encontrar o tempo atual
             target_ms = new_pos * 1000
             while self.page_index + 1 < len(self.lyrics):
                  line = self.lyrics[self.page_index + 1]
                  if target_ms > line.get('end_time', line['time'] + 5000):
                       self.page_index += 2
                  else:
                       break
                       
             print(f"Seek para {new_pos}s")
        except Exception as e:
             print(f"Erro no Seek: {e}")

    def toggle_audio_track(self):
        """Alterna entre Instrumental e Vocal."""
        if not self.current_song: return
        
        if not hasattr(self, 'current_track_type'):
            self.current_track_type = 'instrumental'
        
        inst_path = self.current_song.get('audio_path') 
        orig_path = self.current_song.get('original_audio_path')
        
        current_time_ms = self.get_current_time()
        start_sec = current_time_ms / 1000.0
        
        try:
            target_file = None
            target_type = None
            if self.current_track_type == 'instrumental':
                if orig_path and os.path.exists(orig_path):
                    target_file = orig_path
                    target_type = 'vocal'
            else:
                if inst_path and os.path.exists(inst_path):
                    target_file = inst_path
                    target_type = 'instrumental'
            
            if target_file:
                pygame.mixer.music.load(target_file)
                pygame.mixer.music.set_volume(self.cfg_volume_music)
                pygame.mixer.music.play(start=start_sec)
                self.current_offset_ms = int(start_sec * 1000)
                self.current_track_type = target_type
        except Exception as e:
            print(f"Erro ao alternar áudio: {e}")

    def apply_audio_config(self):
        """Envia configurações da UI para o backend de áudio (Scorer)."""
        self.scorer.set_config(
            self.cfg_mic1_idx,
            self.cfg_mic2_idx,
            self.cfg_monitoring,
            self.cfg_latency_chunk,
            self.cfg_difficulty,
            self.cfg_volume_mic1,
            self.cfg_volume_mic2
        )
        # Atualiza volume da música imediatamente se estiver tocando
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.set_volume(self.cfg_volume_music)

    def handle_input(self, event):
        """Gerencia entradas do usuário para TODOS os estados."""
        if event.type == pygame.KEYDOWN:
            if self.state == "MENU":
                if event.key == pygame.K_RETURN:
                    if self.input_buffer:
                        if self.input_buffer in self.manager.library:
                            self.queue.append(self.input_buffer)
                            print(f"Adicionado {self.input_buffer} à fila.")
                        else:
                            print("Código inválido.")
                        self.input_buffer = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.input_buffer = self.input_buffer[:-1]
                elif event.unicode.isnumeric():
                    self.input_buffer += event.unicode
                elif event.key == pygame.K_c:
                    self.state = "CONFIG"
                    self.input_buffer = "" # Limpa buffer ao entrar config

            elif self.state == "PLAYING":
                if event.key == pygame.K_v:
                    self.toggle_audio_track()
                elif event.key == pygame.K_RIGHT:
                     self.seek_song(10)
                elif event.key == pygame.K_LEFT:
                     self.seek_song(-10)
                elif event.key == pygame.K_RETURN and self.input_buffer:
                     # Adicionar à fila durante jogo
                     if self.input_buffer in self.manager.library:
                        self.queue.append(self.input_buffer)
                        print(f"Adicionado {self.input_buffer} à fila.")
                     self.input_buffer = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.input_buffer = self.input_buffer[:-1]
                elif event.unicode.isnumeric():
                    self.input_buffer += event.unicode

            elif self.state == "SCORE":
                if event.key == pygame.K_RETURN:
                    self.state = "MENU"

            elif self.state == "CONFIG":
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_c:
                    self.state = "MENU" # Voltar
                
                # Atalhos de Configuração Rápida (Teclado)
                # Seta para cima/baixo seleciona item? (UI complexa, vamos usar cliques/teclas simples por enquanto)
                pass
        
        # Eventos de Clique para CONFIG
        if event.type == pygame.MOUSEBUTTONDOWN and self.state == "CONFIG":
            x, y = event.pos
            # Lógica simples de "Hitbox" para a tela de configuração
            # Ex: Slider latencia, monitoramento, etc.
            # Se fosse um app maior, usaria uma lib de UI. Aqui faremos hardcode por zonas.
            
            # Botão Monitoramento (Toggle)
            if 300 <= x <= 320 and 150 <= y <= 170:
                self.cfg_monitoring = not self.cfg_monitoring
            
            # Botão Indicador Ritmo (Toggle)
            if 300 <= x <= 320 and 190 <= y <= 210:
                self.show_rhythm_indicator = not self.show_rhythm_indicator
                
            # Sliders (Lógica aproximada: clique na barra altera valor)
            # Volume Mic 1 (Barra x: 400-700, y: 250)
            if 400 <= x <= 700 and 240 <= y <= 260:
                self.cfg_volume_mic1 = (x - 400) / 300 * 2.0 # Max 2.0
            
            # Volume Mic 2 (Barra x: 400-700, y: 300)
            if 400 <= x <= 700 and 290 <= y <= 310:
                self.cfg_volume_mic2 = (x - 400) / 300 * 2.0
                
            # Volume Musica (Barra x: 400-700, y: 350)
            if 400 <= x <= 700 and 340 <= y <= 360:
                self.cfg_volume_music = (x - 400) / 300
                pygame.mixer.music.set_volume(self.cfg_volume_music)

            # Dificuldade (Ciclar)
            if 400 <= x <= 600 and 400 <= y <= 430:
                modes = ["Fácil", "Normal", "Difícil"]
                curr_idx = modes.index(self.cfg_difficulty)
                self.cfg_difficulty = modes[(curr_idx + 1) % len(modes)]
            
            # Trocar Mic 1 (Ciclar)
            if 400 <= x <= 700 and 500 <= y <= 530:
                self._cycle_mic(1)
            
             # Trocar Mic 2 (Ciclar)
            if 400 <= x <= 700 and 550 <= y <= 580:
                self._cycle_mic(2)
                
            self.apply_audio_config()

    def _cycle_mic(self, mic_num):
        """Cicla entre devices disponiveis."""
        if not self.available_devices: return
        
        current_idx = self.cfg_mic1_idx if mic_num == 1 else self.cfg_mic2_idx
        
        # Encontra posição na lista
        list_idx = -1
        for i, d in enumerate(self.available_devices):
            if d['index'] == current_idx:
                list_idx = i
                break
        
        new_list_idx = (list_idx + 1) % len(self.available_devices)
        new_dev_idx = self.available_devices[new_list_idx]['index']
        
        if mic_num == 1: self.cfg_mic1_idx = new_dev_idx
        else: self.cfg_mic2_idx = new_dev_idx


    def update(self):
        """Loop lógico."""
        if self.state == "PLAYING":
            if not pygame.mixer.music.get_busy():
                self.finish_song()
                return
            
            current_time = self.get_current_time()
            
            # Encontra linha atual
            found_index = -1
            for i, line in enumerate(self.lyrics):
                if current_time >= line['time'] - 200: found_index = i
                else: break
            
            # Paginação
            if not hasattr(self, 'page_index'): self.page_index = 0
            if self.page_index + 1 < len(self.lyrics):
                line_end = self.lyrics[self.page_index + 1].get('end_time', self.lyrics[self.page_index + 1]['time'] + 5000)
                if current_time > line_end: self.page_index += 2
            elif self.page_index < len(self.lyrics):
                 line_end = self.lyrics[self.page_index].get('end_time', self.lyrics[self.page_index]['time'] + 5000)
                 if current_time > line_end: self.page_index += 2

            self.current_line_index = found_index
            
            # Sincroniza Scorer
            if 0 <= self.current_line_index < len(self.lyrics):
                l = self.lyrics[self.current_line_index]
                end_time = l.get('end_time', l['time'] + 5000)
                in_segment = l['time'] <= current_time <= end_time
                self.scorer.set_singing_segment(in_segment)
            else:
                 self.scorer.set_singing_segment(False)

        elif self.state == "MENU":
            if self.queue:
                next_song = self.queue.pop(0)
                self.start_song(next_song)
                self.page_index = 0 
                self.current_track_type = 'instrumental'
                self.current_offset_ms = 0

    def finish_song(self):
        self.scorer.set_paused(True) # Pausa audio processamento de forma segura
        # Aguarda brevemente para thread liberar
        time.sleep(0.1) 
        self.scorer.stop_streams() # Fecha streams agora que está pausado
        self.score_result = self.scorer.get_score()
        self.state = "SCORE"

    def draw(self):
        """Renderização."""
        # Fundo
        if self.state == "CONFIG":
             self.screen.fill((20, 20, 30)) # Fundo escuro tecnico
        else:
            if self.background: self.screen.blit(self.background, (0,0))
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill(COLOR_BG_OVERLAY)
            self.screen.blit(overlay, (0,0))

        if self.state == "MENU":
            self.draw_centered_text("SISTEMA DE KARAOKÊ", -100, color=COLOR_HIGHLIGHT)
            self.draw_centered_text("Digite o código e ENTER para adicionar à fila", -50)
            self.draw_centered_text("[C] para Configurar Áudio / Microfone", 0, size=30, color=COLOR_BLUE)
            
            self.draw_centered_text(f"Fila: {', '.join(self.queue)}", 80)
            
            # Biblioteca
            y_offset = 180
            for code, data in list(self.manager.library.items())[:8]:
                text = f"[{code}] {data['title']} - {data['artist']}"
                surf = self.font_info.render(text, True, COLOR_WHITE)
                self.screen.blit(surf, (50, y_offset))
                y_offset += 30

            input_surf = self.font_info.render(f"Entrada: {self.input_buffer}", True, COLOR_HIGHLIGHT)
            self.screen.blit(input_surf, (50, HEIGHT - 50))

        elif self.state == "PLAYING":
            t_type = getattr(self, 'current_track_type', 'instrumental')
            type_label = "INSTRUMENTAL" if t_type == 'instrumental' else "VOCAL"
            
            info_text = f"{self.current_song['title']} - {self.current_song['artist']} ({type_label})"
            surf = self.font_info.render(info_text, True, COLOR_HIGHLIGHT)
            self.screen.blit(surf, (20, 20))

            # Letras
            current_time = self.get_current_time()
            if hasattr(self, 'page_index') and self.page_index < len(self.lyrics):
                line_data = self.lyrics[self.page_index]
                if 'words' in line_data: self.draw_karaoke_line(line_data, current_time, -40) 
                else: self.draw_centered_text(line_data['text'], -40, 50, COLOR_HIGHLIGHT)

            if hasattr(self, 'page_index') and self.page_index + 1 < len(self.lyrics):
                line_data = self.lyrics[self.page_index + 1]
                if 'words' in line_data: self.draw_karaoke_line(line_data, current_time, 40) 
                else: self.draw_centered_text(line_data['text'], 40, 30, (200,200,200)) 

            # HUD Futurista (VU Meter e Ritmo)
            self.draw_vu_meter_hud()
            if self.show_rhythm_indicator:
                self.draw_rhythm_indicator_hud()
            
            self.draw_ui_progress()

            if self.input_buffer:
                input_surf = self.font_info.render(f"Add Fila: {self.input_buffer}", True, COLOR_WHITE)
                self.screen.blit(input_surf, (20, HEIGHT - 40))

        elif self.state == "SCORE":
            self.draw_centered_text("MÚSICA FINALIZADA", -50)
            self.draw_centered_text(f"Sua Pontuação: {self.score_result}/100", 20, 80, COLOR_HIGHLIGHT)
            self.draw_centered_text("Pressione ENTER para continuar", 100, 30)

        elif self.state == "CONFIG":
            self.draw_config_screen()

        pygame.display.flip()

    def draw_karaoke_line(self, line_data, current_time, y_offset=0):
        words = line_data.get('words', [])
        total_width = 0
        surfaces = []
        space_width = self.font_lyrics.size(" ")[0]
        
        for w in words:
            txt = w['display']
            if current_time >= w['end_ms']: color = COLOR_HIGHLIGHT
            elif current_time >= w['start_ms']: color = (255, 100, 100)
            else: color = (200, 200, 200)
            
            s = self.font_lyrics.render(txt, True, color)
            surfaces.append(s)
            total_width += s.get_width() + space_width
            
        start_x = (WIDTH - total_width) // 2
        y = (HEIGHT // 2) + y_offset
        current_x = start_x
        for s in surfaces:
            self.screen.blit(s, (current_x, y))
            current_x += s.get_width() + space_width

    def draw_vu_meter_hud(self):
        """Desenha um VU Meter visual no canto inferior direito."""
        # Pega volume atual do mic principal
        vol = max(self.scorer.current_volume_mic1, self.scorer.current_volume_mic2)
        # Normaliza visualmente (multiplicador)
        height_val = min(150, int(vol * 5)) 
        
        base_x = WIDTH - 60
        base_y = HEIGHT - 50
        
        # Barra de Fundo
        pygame.draw.rect(self.screen, (50, 50, 50), (base_x, base_y - 150, 30, 150))
        
        # Barra Dinâmica (Gradiente fake)
        if height_val > 0:
            color = COLOR_GREEN
            if height_val > 100: color = COLOR_RED
            elif height_val > 60: color = COLOR_HIGHLIGHT
            
            pygame.draw.rect(self.screen, color, (base_x, base_y - height_val, 30, height_val))
            
            # Efeito "Glow"
            s = pygame.Surface((50, height_val))
            s.set_alpha(50)
            s.fill(color)
            self.screen.blit(s, (base_x - 10, base_y - height_val))

        # Texto "MIC"
        mic_txt = self.font_small.render("MIC", True, COLOR_WHITE)
        self.screen.blit(mic_txt, (base_x + 2, base_y + 5))

    def draw_rhythm_indicator_hud(self):
        """Indicador circular de precisão."""
        acc = self.scorer.get_current_accuracy() # 0.0 a 1.0
        
        cx = WIDTH - 120
        cy = HEIGHT - 125
        radius = 40
        
        # Círculo base
        pygame.draw.circle(self.screen, (50, 50, 50), (cx, cy), radius, 3)
        
        # Círculo de Precisão (Arco ou preenchimento)
        # Cor varia com precisão
        if acc > 0.8: color = COLOR_GREEN
        elif acc > 0.4: color = COLOR_HIGHLIGHT
        else: color = COLOR_RED
        
        # Desenha circulo preenchido proporcional
        fill_rad = int(radius * acc)
        if fill_rad > 0:
             pygame.draw.circle(self.screen, color, (cx, cy), fill_rad)
        
        lbl = self.font_small.render("RITMO", True, COLOR_WHITE)
        self.screen.blit(lbl, (cx - 20, cy + radius + 5))


    def draw_ui_progress(self):
        """Desenha barra de progresso e tempo."""
        if not self.current_song: return
        
        curr_ms = self.get_current_time()
        curr_sec = curr_ms // 1000
        total_sec = self.total_duration // 1000 if self.total_duration > 0 else 0
        
        # Time Text
        def fmt_time(s):
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02}:{sec:02}"
            
        txt = f"{fmt_time(curr_sec)} / {fmt_time(total_sec)}"
        surf = self.font_info.render(txt, True, COLOR_WHITE)
        self.screen.blit(surf, (20, HEIGHT - 70))
        
        # Progress Bar
        bar_w = WIDTH - 200
        bar_h = 10
        bar_x = 100
        bar_y = HEIGHT - 30
        
        pygame.draw.rect(self.screen, (50,50,50), (bar_x, bar_y, bar_w, bar_h))
        
        if self.total_duration > 0:
            pct = min(1.0, curr_ms / self.total_duration)
            fill_w = int(bar_w * pct)
            pygame.draw.rect(self.screen, COLOR_HIGHLIGHT, (bar_x, bar_y, fill_w, bar_h))

    def draw_config_screen(self):
        """Desenha a tela de configuração completas."""
        self.draw_centered_text("CONFIGURAÇÃO DE ÁUDIO", -300, color=COLOR_HIGHLIGHT)
        self.draw_centered_text("[ESC] Voltar", -350, size=30, color=COLOR_WHITE)
        
        # Labels e Controles (Hardcoded layout)
        font = self.font_info
        
        # Coluna Esq: Labels
        lbls = [
            ("Monitorar (Ouvir voz):", 150),
            ("Mostrar Ritmo:", 190),
            (f"Vol Mic 1 ({int(self.cfg_volume_mic1*100)}%):", 250),
            (f"Vol Mic 2 ({int(self.cfg_volume_mic2*100)}%):", 300),
            (f"Vol Música ({int(self.cfg_volume_music*100)}%):", 350),
            (f"Dificuldade: {self.cfg_difficulty}", 410),
            ("Mic 1 Device:", 500),
            ("Mic 2 Device:", 550),
        ]
        
        for text, y in lbls:
            s = font.render(text, True, COLOR_WHITE)
            self.screen.blit(s, (50, y))
            
        # Draw Controls (Simulação visual)
        
        # Checkboxes
        col_chk = COLOR_GREEN if self.cfg_monitoring else (100,100,100)
        pygame.draw.rect(self.screen, col_chk, (300, 150, 20, 20))
        
        col_chk2 = COLOR_GREEN if self.show_rhythm_indicator else (100,100,100)
        pygame.draw.rect(self.screen, col_chk2, (300, 190, 20, 20))
        
        # Sliders (Linha + Bolinha)
        # Mic 1
        pygame.draw.rect(self.screen, (100,100,100), (400, 250, 300, 5))
        pos_x1 = 400 + (self.cfg_volume_mic1 / 2.0) * 300
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x1), 252), 8)
        
        # Mic 2
        pygame.draw.rect(self.screen, (100,100,100), (400, 300, 300, 5))
        pos_x2 = 400 + (self.cfg_volume_mic2 / 2.0) * 300
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x2), 302), 8)

        # Musica
        pygame.draw.rect(self.screen, (100,100,100), (400, 350, 300, 5))
        pos_x_mus = 400 + (self.cfg_volume_music) * 300
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x_mus), 352), 8)
        
        # Dificuldade (Botão)
        pygame.draw.rect(self.screen, (50,50,150), (400, 400, 200, 30))
        d_txt = font.render(self.cfg_difficulty.upper(), True, COLOR_WHITE)
        self.screen.blit(d_txt, (460, 405))
        
        # Devices (Display Name or ID)
        def get_dev_name(idx):
            for d in self.available_devices:
                if d['index'] == idx: return d['name'][:40]
            return "Nenhum"
            
        # Mic 1 Sel
        pygame.draw.rect(self.screen, (50,50,50), (400, 500, 300, 30))
        n1 = font.render(get_dev_name(self.cfg_mic1_idx), True, COLOR_WHITE)
        self.screen.blit(n1, (410, 505))
        
        # Mic 2 Sel
        pygame.draw.rect(self.screen, (50,50,50), (400, 550, 300, 30))
        n2 = font.render(get_dev_name(self.cfg_mic2_idx), True, COLOR_WHITE)
        self.screen.blit(n2, (410, 555))
        
        # VU Meters na Config para teste
        # Mic 1
        v1 = min(150, int(self.scorer.current_volume_mic1 * 10))
        pygame.draw.rect(self.screen, COLOR_GREEN, (720, 500, v1, 30))
        
        # Mic 2
        v2 = min(150, int(self.scorer.current_volume_mic2 * 10))
        pygame.draw.rect(self.screen, COLOR_GREEN, (720, 550, v2, 30))


    def draw_centered_text(self, text, y_offset=0, size=None, color=COLOR_WHITE):
        """
        Função auxiliar para desenhar texto centralizado.
        """
        font = self.font_lyrics
        if size: font = pygame.font.Font(None, size)
            
        surface = font.render(text, True, color)
        rect = surface.get_rect(center=(WIDTH // 2, HEIGHT // 2 + y_offset))
        self.screen.blit(surface, rect)

    def run(self):
        """Loop principal com tratamento de falhas."""
        try:
            running = True
            while running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    self.handle_input(event)

                self.update()
                self.draw()
                self.clock.tick(FPS)
        except Exception as e:
            print(f"CRASH DETECTADO: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("Encerrando aplicação...")
            self.scorer.shutdown()
            pygame.quit()
            sys.exit()

if __name__ == "__main__":
    app = KaraokePlayer()
    app.run()

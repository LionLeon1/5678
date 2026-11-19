"""
Apex Life: F1 Open World v2.0
Motor 3D ligero propio (proyección perspectiva + iluminación por profundidad + rivales 3D + DRS) sobre Kivy.
"""
import json
import math
import os
import random
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, Triangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager


def load_game_data():
    path = os.path.join(os.path.dirname(__file__), "apex_life_f1.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "driver_defaults": {
            "name": "Piloto F1",
            "team": "Scuderia Apex",
            "money": 350000,
            "reputation": 60,
            "fitness": 85,
            "energy": 100,
            "championship_points": 0,
            "day": 1,
            "garage": ["F1-26 Monoplaza"]
        },
        "locations": [
            {"id": "apartment", "name": "Penthouse en Mónaco", "type": "home", "action_label": "Dormir (+100% Energía, +1 Día)"},
            {"id": "paddock", "name": "Circuito de Mónaco (Carrera 3D)", "type": "race", "action_label": "Salir a Pista 3D"},
            {"id": "gym", "name": "Centro de Alto Rendimiento", "type": "training", "action_label": "Entrenar (-20 Energía, +10 Físico)"},
            {"id": "casino", "name": "Gala VIP y Patrocinadores", "type": "social", "action_label": "Evento VIP (-15 Energía, +$75,000)"},
            {"id": "dealership", "name": "Concesionario", "type": "shop", "action_label": "Comprar Hypercar ($250,000)"}
        ]
    }


class Apex3DEngineWidget(BoxLayout):
    """Motor 3D mejorado: pista curva, edificios a ambos lados, rivales 3D y DRS."""

    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.speed = 0.0
        self.base_max_speed = 325.0
        self.drs_active = False
        self.car_x = 0.0
        self.z_offset = 0.0
        self.distance = 0.0
        self.steer = 0.0
        self.accelerating = False
        self.braking = False
        self.overtakes = 0
        self.rivals = []
        self.event = None

        controls = BoxLayout(size_hint=(1, 0.22), pos_hint={"y": 0}, spacing=8, padding=8)
        btn_left = Button(text="< IZQ", background_color=(0.18, 0.2, 0.28, 0.85))
        btn_right = Button(text="DER >", background_color=(0.18, 0.2, 0.28, 0.85))
        btn_brake = Button(text="FRENO", background_color=(0.82, 0.14, 0.14, 0.88))
        btn_gas = Button(text="ACELERAR", background_color=(0.12, 0.72, 0.28, 0.88))
        btn_drs = Button(text="DRS", background_color=(0.1, 0.55, 0.9, 0.9))
        btn_exit = Button(text="SALIR", background_color=(0.35, 0.35, 0.4, 0.9))

        btn_left.bind(on_press=lambda *_: setattr(self, "steer", -1.0),
                      on_release=lambda *_: setattr(self, "steer", 0.0))
        btn_right.bind(on_press=lambda *_: setattr(self, "steer", 1.0),
                       on_release=lambda *_: setattr(self, "steer", 0.0))
        btn_gas.bind(on_press=lambda *_: setattr(self, "accelerating", True),
                     on_release=lambda *_: setattr(self, "accelerating", False))
        btn_brake.bind(on_press=lambda *_: setattr(self, "braking", True),
                       on_release=lambda *_: setattr(self, "braking", False))
        btn_drs.bind(on_press=lambda *_: setattr(self, "drs_active", True),
                     on_release=lambda *_: setattr(self, "drs_active", False))
        btn_exit.bind(on_press=self.exit_track)

        for b in (btn_left, btn_right, btn_brake, btn_gas, btn_drs, btn_exit):
            controls.add_widget(b)
        self.add_widget(controls)

        self.hud = Label(
            text="0 km/h | DRS: OFF | Adelantamientos: 0",
            size_hint=(1, 0.1),
            pos_hint={"top": 1},
            font_size="18sp",
            bold=True,
            color=(1, 1, 1, 1),
        )
        self.add_widget(self.hud)

    def start(self):
        self.speed = 0.0
        self.car_x = 0.0
        self.distance = 0.0
        self.overtakes = 0
        self.rivals = [
            {"x": random.choice([-0.55, 0.0, 0.55]), "z": 16.0 + i * 14.0, "color": c}
            for i, c in enumerate([(0.1, 0.4, 0.95), (0.95, 0.5, 0.05), (0.05, 0.75, 0.65)])
        ]
        if not self.event:
            self.event = Clock.schedule_interval(self.update, 1.0 / 60.0)

    def stop(self):
        if self.event:
            self.event.cancel()
            self.event = None

    def exit_track(self, *_):
        self.stop()
        reward = int(self.distance * 20 + self.overtakes * 15000)
        self.app_ref.state["money"] += reward
        self.app_ref.state["energy"] = max(0, self.app_ref.state["energy"] - 15)
        self.app_ref.state["reputation"] += 5 + self.overtakes * 2
        self.app_ref.sm.current = "city"
        self.app_ref.city_screen.refresh_ui(
            f"Carrera terminada: +${reward:,} | {self.overtakes} adelantamientos."
        )

    def project(self, x, y, z, w, h, fov=280.0):
        scale = fov / max(z, 0.15)
        return w * 0.5 + x * scale, h * 0.53 + y * scale, scale

    def update(self, dt):
        max_spd = self.base_max_speed + (35.0 if self.drs_active else 0.0)
        if self.accelerating:
            accel = 175.0 if self.drs_active else 140.0
            self.speed = min(max_spd, self.speed + accel * dt)
        elif self.braking:
            self.speed = max(0.0, self.speed - 260.0 * dt)
        else:
            self.speed = max(0.0, self.speed - 45.0 * dt)

        self.car_x = max(-1.05, min(1.05, self.car_x + self.steer * dt * (0.9 + self.speed / 260.0)))
        self.z_offset = (self.z_offset + self.speed * dt * 0.16) % 4.0
        self.distance += (self.speed / 3.6) * dt

        # Actualizar rivales 3D
        rel_speed = max(10.0, (self.speed - 190.0)) * dt * 0.12
        for r in self.rivals:
            r["z"] -= rel_speed
            if r["z"] < 1.8:
                if abs(r["x"] - self.car_x) < 0.35:
                    self.speed = max(40.0, self.speed * 0.55)
                else:
                    self.overtakes += 1
                r["z"] = 42.0 + random.uniform(0, 12.0)
                r["x"] = random.choice([-0.65, 0.0, 0.65])

        drs_txt = "ON" if self.drs_active else "OFF"
        self.hud.text = f"{int(self.speed)} km/h | DRS: {drs_txt} | Dist: {int(self.distance)}m | Adelant.: {self.overtakes}"
        self.render_3d()

    def render_3d(self):
        self.canvas.before.clear()
        w, h = self.width, self.height
        horizon_y = h * 0.53

        with self.canvas.before:
            # Cielo con degradado en bandas (atardecer Mónaco)
            Color(0.05, 0.09, 0.22, 1)
            Rectangle(pos=(0, horizon_y + (h - horizon_y) * 0.5), size=(w, (h - horizon_y) * 0.5))
            Color(0.14, 0.22, 0.38, 1)
            Rectangle(pos=(0, horizon_y), size=(w, (h - horizon_y) * 0.5))

            # Suelo mar/césped
            Color(0.08, 0.16, 0.18, 1)
            Rectangle(pos=(0, 0), size=(w, horizon_y))

            road_half_w = 2.7
            segments = 22
            for i in range(segments, 0, -1):
                z1 = i * 1.9 - (self.z_offset * 0.45)
                z2 = (i + 1) * 1.9 - (self.z_offset * 0.45)
                if z1 <= 0.35:
                    continue

                curve1 = math.sin((self.distance * 0.009) + i * 0.22) * 1.6
                curve2 = math.sin((self.distance * 0.009) + (i + 1) * 0.22) * 1.6

                x1 = curve1 - self.car_x * 2.2
                x2 = curve2 - self.car_x * 2.2

                p1l = self.project(-road_half_w + x1, -1.65, z1, w, h)
                p1r = self.project(road_half_w + x1, -1.65, z1, w, h)
                p2l = self.project(-road_half_w + x2, -1.65, z2, w, h)
                p2r = self.project(road_half_w + x2, -1.65, z2, w, h)

                depth_fade = max(0.35, 1.0 - (i / float(segments)) * 0.55)
                base_shade = (0.24 if i % 2 == 0 else 0.19) * depth_fade
                Color(base_shade, base_shade, base_shade + 0.03, 1)
                Triangle(points=[p1l[0], p1l[1], p1r[0], p1r[1], p2r[0], p2r[1]])
                Triangle(points=[p1l[0], p1l[1], p2r[0], p2r[1], p2l[0], p2l[1]])

                # Pianos F1
                Color(0.92 * depth_fade, 0.12, 0.12, 1) if i % 2 == 0 else Color(0.92 * depth_fade, 0.92 * depth_fade, 0.92 * depth_fade, 1)
                Line(points=[p1l[0], p1l[1], p2l[0], p2l[1]], width=2.8)
                Line(points=[p1r[0], p1r[1], p2r[0], p2r[1]], width=2.8)

                # Edificios 3D a ambos lados
                if i % 3 == 0:
                    bl_top = self.project(-road_half_w - 2.6 + x1, 2.8, z1, w, h)
                    br_top = self.project(road_half_w + 2.6 + x1, 2.4, z1, w, h)
                    bw = max(12, 420 / max(z1, 1.0))
                    Color(0.22 * depth_fade, 0.27 * depth_fade, 0.38 * depth_fade, 0.95)
                    Rectangle(pos=(bl_top[0] - bw * 0.5, p1l[1]), size=(bw, max(8, bl_top[1] - p1l[1])))
                    Color(0.28 * depth_fade, 0.25 * depth_fade, 0.36 * depth_fade, 0.95)
                    Rectangle(pos=(br_top[0] - bw * 0.5, p1r[1]), size=(bw, max(8, br_top[1] - p1r[1])))

            # Dibujar rivales 3D ordenados por distancia
            for r in sorted(self.rivals, key=lambda item: item["z"], reverse=True):
                if 1.5 < r["z"] < 40.0:
                    curve_r = math.sin((self.distance * 0.009) + (r["z"] / 1.9) * 0.22) * 1.6
                    rx = (r["x"] * 2.0) + curve_r - self.car_x * 2.2
                    px, py, sc = self.project(rx, -1.65, r["z"], w, h)
                    cw = max(10, sc * 0.95)
                    ch = max(6, sc * 0.45)
                    Color(*r["color"], 1)
                    Rectangle(pos=(px - cw * 0.5, py), size=(cw, ch))
                    Color(0.08, 0.08, 0.08, 1)
                    Rectangle(pos=(px - cw * 0.65, py), size=(cw * 0.2, ch * 0.8))
                    Rectangle(pos=(px + cw * 0.45, py), size=(cw * 0.2, ch * 0.8))

            # Monoplaza del jugador
            cx = w * 0.5
            cy = h * 0.24
            Color(0.88, 0.07, 0.12, 1)
            Rectangle(pos=(cx - 32, cy), size=(64, 24))
            Color(0.08, 0.08, 0.08, 1)
            Rectangle(pos=(cx - 44, cy - 4), size=(15, 26))
            Rectangle(pos=(cx + 29, cy - 4), size=(15, 26))
            Color(0.15, 0.85, 1.0, 1) if self.drs_active else Color(0.95, 0.95, 0.95, 1)
            Rectangle(pos=(cx - 34, cy + 22), size=(68, 7))


class CityScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.root_box = BoxLayout(orientation="vertical", padding=16, spacing=10)
        self.stats_label = Label(size_hint=(1, 0.18), font_size="15sp", halign="center")
        self.msg_label = Label(
            text="Mónaco Mundo Abierto — Elige tu próxima actividad.",
            size_hint=(1, 0.12),
            color=(0.3, 0.92, 0.55, 1),
        )
        self.root_box.add_widget(self.stats_label)
        self.root_box.add_widget(self.msg_label)

        for loc in self.app_ref.data["locations"]:
            btn = Button(
                text=f"{loc['name']} — {loc['action_label']}",
                size_hint=(1, 0.13),
                background_color=(0.14, 0.22, 0.36, 1),
            )
            btn.bind(on_press=lambda _, l=loc: self.do_action(l))
            self.root_box.add_widget(btn)

        self.add_widget(self.root_box)
        self.refresh_ui()

    def refresh_ui(self, message=None):
        s = self.app_ref.state
        self.stats_label.text = (
            f"Día {s['day']} | {s['team']} | Dinero: ${s['money']:,}\n"
            f"Reputación: {s['reputation']} | Físico: {s['fitness']} | Energía: {s['energy']}%"
        )
        if message:
            self.msg_label.text = message

    def do_action(self, loc):
        s = self.app_ref.state
        ltype = loc["type"]
        if ltype == "home":
            s["energy"] = 100
            s["day"] += 1
            self.refresh_ui("Descansaste en tu penthouse. Energía al 100%.")
        elif ltype == "race":
            if s["energy"] < 15:
                self.refresh_ui("Necesitas descansar antes de salir a pista.")
                return
            self.app_ref.sm.current = "track"
            self.app_ref.track_widget.start()
        elif ltype == "training":
            if s["energy"] < 20:
                self.refresh_ui("Demasiado cansado para entrenar.")
                return
            s["energy"] -= 20
            s["fitness"] = min(100, s["fitness"] + 10)
            self.refresh_ui("Entrenamiento completado. +10 Físico.")
        elif ltype == "social":
            if s["energy"] < 15:
                self.refresh_ui("Sin energía para eventos VIP.")
                return
            s["energy"] -= 15
            s["reputation"] += 15
            s["money"] += 75000
            self.refresh_ui("Evento VIP exitoso: +$75,000 y +15 Reputación.")
        elif ltype == "shop":
            if s["money"] < 250000:
                self.refresh_ui("Necesitas $250,000 para comprar un Hypercar.")
                return
            s["money"] -= 250000
            s["reputation"] += 30
            self.refresh_ui("¡Nuevo Hypercar en tu garaje! +30 Reputación.")


class TrackScreen(Screen):
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.widget_3d = Apex3DEngineWidget(app_ref)
        self.add_widget(self.widget_3d)


class ApexLifeApp(App):
    def build(self):
        Window.clearcolor = (0.05, 0.07, 0.12, 1)
        self.data = load_game_data()
        self.state = dict(self.data["driver_defaults"])
        self.sm = ScreenManager()
        self.city_screen = CityScreen(self, name="city")
        self.track_screen = TrackScreen(self, name="track")
        self.track_widget = self.track_screen.widget_3d
        self.sm.add_widget(self.city_screen)
        self.sm.add_widget(self.track_screen)
        return self.sm


if __name__ == "__main__":
    ApexLifeApp().run()

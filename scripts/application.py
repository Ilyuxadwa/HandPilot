from unified_ui import App, Settings, tools
import flet as ft

import info
import main
import utils



def loading_ui(app):
    app.add_element(app.alignment("rcenter", ft.Text("Your assistant is preparing!", style = tools.primary_text_style(app, 80)), width = tools.adapt_dimensions(app, "w", 100), spacing = tools.adapt_dimensions(app, "w", 4), expand = True))
    app.add_element(app.alignment("rcenter", ft.Text("Waiting for initialization...", style = tools.secondary_text_style(app, 18)), width = tools.adapt_dimensions(app, "w", 100), spacing = tools.adapt_dimensions(app, "w", 4), expand = True))


def main_ui(app):
    def toggle_text(txt, font_size = 36):
        return ft.Text(txt, style = tools.primary_text_style(app, font_size))

    def profiler_row(name):
        row = None

        def on_change():
            main.toggle_game_profiler(name, row.controls[2].value)
    
        row = app.alignment("rcenter", ft.IconButton(utils.icon("settings"), style = tools.main_button_style(app, 18)), app.alignment("rcenter", toggle_text(name, 28), width = tools.adapt_dimensions(app, "w", 20)), tools.switch(app, 18, on_change=on_change), spacing = tools.adapt_dimensions(app, "w", 6))
        return row


    icon, msg = utils.welcome_message()
    app.add_element(app.alignment("rcenter", ft.Icon(icon, color = app.theme.primary, size = tools.adapt_dimensions(app, "w", 7)), ft.Text(msg, style = tools.primary_text_style(app, 48, weight = ft.FontWeight.BOLD)), width = tools.adapt_dimensions(app, "w", 100)))

    voice_toggle = tools.switch(app, 24, on_change = lambda: main.toggle_voice_helper(voice_toggle.value))
    gestures_toggle = tools.switch(app, 24, on_change = lambda: main.toggle_gestures_controls(gestures_toggle.value))

    app.add_element(app.alignment("rspace_evenly", 
                        app.alignment("rcenter", toggle_text("Voice Helper"), voice_toggle),
                        app.alignment("rcenter", toggle_text("Gestures Control"), gestures_toggle)))
    app.add_devider()
    app.add_element(app.alignment("rcenter", ft.Text("Game Profilers", style = tools.primary_text_style(app, 36, weight = ft.FontWeight.BOLD), height = tools.adapt_dimensions(app, "h", 12))))

    Profilers = [profiler_row(name) for name in main.profilers]
    app.add_element(app.alignment("cstart", *Profilers, spacing = tools.adapt_dimensions(app, "h", 6)))
    
def build():
    app = App()

    app.set_version(info.VERSION)
    app.set_orientation("portrait")

    app.allow_delete_saved()

    app.add_page("loading_page", loading_ui)
    app.add_page("main_page", main_ui)

    app.set_async_next(main.start)
    app.run(info.APP_NAME)
from unified_ui import App, Settings, tools
import flet as ft

import info
import main
import utils



def loading_ui(app):
    app.add_element(app.alignment("rcenter", ft.Text("Your assistant is preparing!", style = tools.primary_text_style(app, 80)), width = tools.adapt_dimensions(app, "w", 100), spacing = tools.adapt_dimensions(app, "w", 4), expand = True))
    app.add_element(app.alignment("rcenter", ft.Text("Waiting for initialization...", style = tools.secondary_text_style(app, 18)), width = tools.adapt_dimensions(app, "w", 100), spacing = tools.adapt_dimensions(app, "w", 4), expand = True))


def main_ui(app):
    def toggle_text(txt):
        return ft.Text(txt, style = tools.primary_text_style(app, 32))
    
    icon, msg = utils.welcome_message()
    app.add_element(app.alignment("rcenter", ft.Icon(icon, color = app.theme.primary, size = tools.adapt_dimensions(app, "w", 7)), ft.Text(msg, style = tools.primary_text_style(app, 48, weight = ft.FontWeight.BOLD)), width = tools.adapt_dimensions(app, "w", 100)))

    voice_toggle = tools.switch(app, 18, on_change = lambda: main.toggle_voice_helper(voice_toggle.value))
    gestures_toggle = tools.switch(app, 18, on_change = lambda: main.toggle_gestures_controls(gestures_toggle.value))

    app.add_element(app.alignment("rspace_evenly", 
                        app.alignment("rcenter", toggle_text("Voice Helper"), voice_toggle),
                        app.alignment("rcenter", toggle_text("Gestures Control"), gestures_toggle)))
    
def build():
    app = App()

    app.set_version(info.VERSION)
    app.set_orientation("portrait")

    app.allow_delete_saved()

    app.add_page("loading_page", loading_ui)
    app.add_page("main_page", main_ui)

    app.set_async_next(main.start)
    app.run(info.APP_NAME)
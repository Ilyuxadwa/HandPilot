from unified_ui import App, Settings, tools
import flet as ft

import info
import main
import utils

def main_ui(app):
    icon, msg = utils.welcome_message()
    app.add_element(app.alignment("rcenter", ft.Icon(icon, color = app.theme.primary, size = tools.adapt_dimensions(app, "w", 5)), ft.Text(msg, style = tools.primary_text_style(app, 48)), width = tools.adapt_dimensions(app, "w", 100)))

def build():
    app = App()

    app.set_version(info.VERSION)
    app.set_orientation("portrait")

    app.allow_delete_saved()

    app.add_page("main_page", main_ui)

    app.set_async_next(main.start)
    app.run(info.APP_NAME)
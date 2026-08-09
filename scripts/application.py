from unified_ui import App, Settings, tools
import flet as ft

import info
import main

def main_ui(app):
    app.add_element(ft.Text("App started", style = tools.primary_text_style(app, 48)))
    
def build():
    app = App()

    app.set_size("1/4")
    app.set_version(info.VERSION)
    app.set_orientation("portrait")

    app.add_saved_keys("reg_data", "registered", "registered_version", "statistics", "daily_goals", "weekly_goals", "custom_goals", "active_goals", "gained_achievements")
    app.allow_delete_saved()

    app.add_page("main_page", main_ui)

    app.set_async_next(main.start)
    app.run(info.APP_NAME)
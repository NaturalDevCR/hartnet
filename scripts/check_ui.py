"""Local UI smoke check. Never activates DMX or sends discovery packets."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "test-results"
OUTPUT.mkdir(exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=True
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto("http://127.0.0.1:8099")
    page.get_by_role("button", name="Importar configuración").click()
    page.get_by_role("button", name="Cargar configuración de ejemplo").click()
    page.get_by_role("button", name="Revisar importación").click()
    page.get_by_role("heading", name="8 equipos listos para revisar").wait_for()
    page.get_by_role("button", name="Reemplazar patch con esta importación").click()
    page.get_by_role("heading", name="Equipos", exact=True).wait_for()
    assert page.locator(".equipment-row").count() == 8
    assert page.locator("#stat-frames").inner_text() == "0"
    assert page.locator("#output-badge").inner_text() == "Salida detenida"
    page.screenshot(path=str(OUTPUT / "hartnet-desktop.png"), full_page=True)
    page.locator(".equipment-row").nth(3).click()
    assert page.locator("#inspector input[type=number]").count() == 1
    control = page.locator("#inspector input[type=number]")
    control.fill("87")
    control.press("Tab")
    page.wait_for_function("document.querySelector('#inspector input[type=number]').value === '87'")
    page.get_by_role("button", name="Patch de universos").click()
    assert page.locator(".slot").count() == 512
    assert page.locator(".slot.used").count() == 26
    page.get_by_role("button", name="Biblioteca de perfiles").click()
    page.get_by_role("button", name="Crear perfil").click()
    page.locator('#editor input[name="name"]').fill("Generic pan 16 bit")
    page.locator('[data-field="slots"]').fill("1,8")
    page.locator("#editor summary").click()
    page.locator('[data-field="max"]').fill("65535")
    page.get_by_role("button", name="Guardar cambios").click()
    page.locator("#editor").wait_for(state="hidden")
    page.get_by_role("heading", name="Generic pan 16 bit").wait_for()
    # Re-import the unchanged real example, leaving a clean preview with zero output.
    page.get_by_role("button", name="Importar configuración").click()
    page.get_by_role("button", name="Cargar configuración de ejemplo").click()
    page.get_by_role("button", name="Revisar importación").click()
    page.get_by_role("button", name="Reemplazar patch con esta importación").click()
    page.get_by_role("heading", name="Equipos", exact=True).wait_for()
    for width in (390, 320):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Patch de universos").click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Equipos", exact=False).first.click()
    page.screenshot(path=str(OUTPUT / "hartnet-mobile.png"), full_page=True)
    assert not errors, errors
    assert page.locator("#stat-frames").inner_text() == "0"
    browser.close()
print("UI passed: import, preview, patch, scalar controls, profile editor, 1440/390/320px; zero DMX packets.")

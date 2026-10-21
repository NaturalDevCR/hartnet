"""Local UI smoke check. Never activates DMX or sends discovery packets."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

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
    page.locator("#language").select_option("en")
    page.get_by_role("button", name="Import configuration").click()
    page.get_by_role("button", name="Load example configuration").click()
    page.get_by_role("button", name="Review import").click()
    page.get_by_role("heading", name="8 fixtures ready for review").wait_for()
    page.get_by_role("button", name="Replace patch with this import").click()
    page.get_by_role("heading", name="Fixtures", exact=True).wait_for()
    assert page.locator(".equipment-row").count() == 8
    assert page.locator("#stat-frames").inner_text() == "0"
    assert page.locator("#output-badge").inner_text() == "Output stopped"
    page.screenshot(path=str(OUTPUT / "hartnet-desktop.png"), full_page=True)
    page.locator(".equipment-row").nth(3).click()
    assert page.locator("#inspector input[type=number]").count() == 1
    control = page.locator("#inspector input[type=number]")
    control.fill("87")
    control.press("Tab")
    page.wait_for_function("document.querySelector('#inspector input[type=number]').value === '87'")
    page.get_by_role("button", name="Universe patch").click()
    assert page.locator(".slot").count() == 512
    assert page.locator(".slot.used").count() == 26
    page.get_by_role("button", name="Profile library").click()
    page.get_by_role("button", name="Create profile").click()
    page.locator('#editor input[name="name"]').fill("Generic pan 16 bit")
    page.locator('[data-field="slots"]').fill("1,8")
    page.locator("#editor summary").click()
    page.locator('[data-field="max"]').fill("65535")
    page.get_by_role("button", name="Save changes").click()
    page.locator("#editor").wait_for(state="hidden")
    page.get_by_role("heading", name="Generic pan 16 bit").wait_for()
    # Language switching preserves user data, supports editors and survives a reload.
    page.locator("#language").select_option("es")
    page.get_by_role("heading", name="Biblioteca de perfiles", exact=True).wait_for()
    page.get_by_role("heading", name="Generic pan 16 bit").wait_for()
    page.get_by_role("button", name="＋ Crear perfil").click()
    assert page.locator("#editor-title").inner_text() == "Crear perfil"
    page.get_by_role("button", name="Cerrar", exact=True).click()
    page.reload()
    page.get_by_role("heading", name="Equipos", exact=True).wait_for()
    assert page.locator("html").get_attribute("lang") == "es"
    page.locator('[data-tab="settings"]').click()
    page.get_by_role("heading", name="Nodos y conexiones").wait_for()
    page.get_by_role("button", name="＋ Agregar nodo").click()
    page.locator('#editor input[name="host"]').fill("invalid")
    page.get_by_role("button", name="Guardar cambios").click()
    expect(page.locator("#editor-error")).to_contain_text("IPv4 requerida")
    page.get_by_role("button", name="Cerrar", exact=True).click()
    page.locator("#language").select_option("en")
    page.get_by_role("heading", name="Nodes and connections").wait_for()
    page.get_by_role("button", name="＋ Add node").click()
    page.locator('#editor input[name="host"]').fill("invalid")
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("#editor-error")).to_contain_text("IPv4 address required")
    page.get_by_role("button", name="Close", exact=True).click()
    # Re-import the unchanged public example, leaving a clean preview with zero output.
    page.get_by_role("button", name="Import configuration").click()
    page.get_by_role("button", name="Load example configuration").click()
    page.get_by_role("button", name="Review import").click()
    page.get_by_role("button", name="Replace patch with this import").click()
    page.get_by_role("heading", name="Fixtures", exact=True).wait_for()
    for width in (390, 320):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Universe patch").click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Fixtures", exact=False).first.click()
    page.screenshot(path=str(OUTPUT / "hartnet-mobile.png"), full_page=True)
    assert not errors, errors
    assert page.locator("#stat-frames").inner_text() == "0"
    browser.close()
print(
    "UI passed: English/Spanish, persistence, user data, import, patch, controls, "
    "profile editor, 1440/390/320px; zero DMX packets."
)

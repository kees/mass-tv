# Mass TV build, test, and deploy.
#
# Off-device (no Roku needed):
#   make build           debug build (bs_const DEBUG=true) into build/debug
#   make release         release build (DEBUG=false) into build/release
#   make lint            BrighterScript diagnostics + bslint
#   make unit            unit tests of source/lib under brs-cli
#   make e2e             whole app in the brs-cli simulator against tools/fake_ma.py
#   make check           lint + unit + e2e
#   make zip zip-release sideload packages in out/
#   make test-media      synthetic test tracks + cover art into test-media/
#   make fake-ma         run the fake MA server (ROKU=<name> for its ECP target;
#                        CODEC=flac-44k|flac-48k|mp3|aac|flac-96k24,
#                        HTTP_PROFILE=no_content_length|chunked|forced_content_length)
#
# Device: name the Roku with ROKU=<name> (required, e.g. ROKU=livingroom); its
# address is ROKU_<NAME>_IP and the dev password ROKU_DEV_PASSWORD, from
# the environment or .env:
#   make deploy          sideload the debug build
#   make deploy-release  sideload the release build
#   make console         stream the BrightScript console (port 8085) to logs/
#   make logs            follow the app's debug log (port 8889) to logs/
#   make screenshot      capture the screen to logs/
#   make collector       run the push log collector on this host (port 8765)

-include .env
# The named Roku's address variable, passed on so tools/roku.py (which
# resolves ROKU itself) finds it; without ROKU, device tools refuse.
ROKU_IP_VAR := $(if $(ROKU),$(shell echo ROKU_$(ROKU)_IP | tr a-z A-Z))
export ROKU ROKU_DEV_PASSWORD $(ROKU_IP_VAR)

BSC := npx bsc
BRS := node_modules/.bin/brs-cli
PY := python3

.PHONY: all build release lint unit e2e check zip zip-release deploy deploy-release console logs screenshot collector test-media fake-ma assets images font clean

all: check

# Generated assets, not kept in git: the images (tools/make_images.py)
# and the bundled font (tools/make_font.py). Each is remade only when its
# script, inputs, source fonts, or tool versions change. The source fonts
# (pinned in fonts/sources.txt) are downloaded only when missing or when
# a pin changes; fontTools and Pillow (tools/requirements.txt) go into
# .venv. Grouped targets (&:) need GNU Make 4.3 or newer.
VENV := .venv
VPY := $(VENV)/bin/python
VENV_STAMP := $(VENV)/.installed
FONT_SOURCES := fonts/source/.fetched
IMAGES := $(addprefix src/images/,fade_bottom.png fade_top.png \
	focus_ring.9.png focus_row.9.png icon_focus_fhd.png icon_focus_hd.png \
	logo_settings_fhd.png logo_settings_hd.png pill.9.png \
	placeholder_card.png placeholder_card_letter.png placeholder_header.png \
	placeholder_nowplaying.png placeholder_row.png spinner.png \
	splash_fhd.png splash_hd.png wordmark_nav_fhd.png wordmark_nav_hd.png)
FONTS := src/fonts/MassTVText-Regular.ttf
ASSETS := $(IMAGES) $(FONTS)

assets: $(ASSETS)
images: $(IMAGES)
font: $(FONTS)

$(VENV_STAMP): tools/requirements.txt
	$(PY) -m venv $(VENV)
	$(VPY) -m pip install --quiet --disable-pip-version-check -r tools/requirements.txt
	touch $@

$(FONT_SOURCES): fonts/sources.txt
	$(PY) tools/make_font.py fetch
	touch $@

$(FONTS) &: tools/make_font.py fonts/extra-chars.txt $(FONT_SOURCES) $(VENV_STAMP)
	$(VPY) tools/make_font.py build

$(IMAGES) &: tools/make_images.py $(FONT_SOURCES) $(VENV_STAMP)
	$(VPY) tools/make_images.py --force --expect "$(notdir $(IMAGES))" src/images

build: $(ASSETS)
	$(BSC) --project bsconfig.json
	$(PY) tools/set_bs_const.py build/debug/manifest DEBUG=true

release: $(ASSETS)
	$(BSC) --project bsconfig.release.json
	$(PY) tools/set_bs_const.py build/release/manifest DEBUG=false

lint: $(ASSETS)
	$(BSC) --project bsconfig.json --stagingDir build/lint

unit: $(ASSETS)
	rm -rf build/unit build/unit.log
	$(BSC) --project bsconfig.unit.json
	cd build/unit && ../../$(BRS) source/bslib.brs source/lib/*.brs source/tests/*.brs | tee ../unit.log
	grep -q "UNIT_RESULT=PASS" build/unit.log

e2e: zip
	$(PY) tools/e2e_sim.py --zip out/masstv-debug.zip

check: lint unit e2e

zip: build
	mkdir -p out
	rm -f out/masstv-debug.zip
	cd build/debug && zip -qr ../../out/masstv-debug.zip . -x '*.map'

zip-release: release
	mkdir -p out
	rm -f out/masstv-release.zip
	cd build/release && zip -qr ../../out/masstv-release.zip .

deploy: zip
	$(PY) tools/roku.py sideload out/masstv-debug.zip

deploy-release: zip-release
	$(PY) tools/roku.py sideload out/masstv-release.zip

console:
	$(PY) tools/roku.py console

logs:
	$(PY) tools/roku.py logs --follow

screenshot:
	$(PY) tools/roku.py screenshot

collector:
	$(PY) tools/log_collector.py

CODEC ?= flac-44k
HTTP_PROFILE ?= no_content_length

test-media:
	$(PY) tools/make_test_media.py

fake-ma:
	$(if $(ROKU),,$(error name the Roku: ROKU=<name>))
	$(PY) tools/fake_ma.py --roku $($(ROKU_IP_VAR)) --codec $(CODEC) --http-profile $(HTTP_PROFILE)

clean:
	rm -rf build out

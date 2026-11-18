help:
	@echo "make help     -- print this help"
	@echo "make generate -- regenerate the json"

generate:
	wget https://hugovk.dev/top-pypi-packages/top-pypi-packages.min.json -O top-pypi-packages.json
	python3 generate.py

import config

print("CITIES length:", len(config.CITIES))
print("CITY_SLUGS length:", len(config.CITY_SLUGS))

print("\nCITY_SLUG_ALIASES:")
for k, v in config.CITY_SLUG_ALIASES.items():
    print(f"  {k}: {v}")


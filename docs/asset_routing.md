# Topic-Aware Asset Routing

The **Asset Router** replaces the single-provider asset pipeline with an
extensible routing architecture.  Given a video's topic, it selects the
best provider(s) for searching and downloading media assets.

## Architecture

```
Video Topic (e.g. "The Fermi Paradox")
       │
       ▼
┌──────────────────┐
│  TopicClassifier  │  ← Keyword-based category assignment
└──────┬───────────┘
       │ category (e.g. "Space")
       ▼
┌──────────────────┐
│   AssetRouter    │  ← Chooses provider by category priority
└──────┬───────────┘
       │
       ├── [nasa]      → NasaMediaProvider (stub)
       ├── [pixabay]   → PixabayProvider (stub)
       └── [pexels]    → PexelsProvider (wrapped in AssetLibrary)
```

### Components

1. **TopicClassifier** — Maps a video topic string (e.g. *"The Rise and
   Fall of the Roman Empire"*) to a category (e.g. *"History"*) using
   keyword overlap scoring.

2. **AssetRouter** — Given a category, maintains a priority-ordered list
   of providers.  Iterates through them on `search()`, returning the first
   non-empty result.

3. **StubAssetProvider** — Base class for providers not yet backed by a
   real API.  Returns empty lists on `search()` and raises
   `NotImplementedError` on `download()`.

### Provider Registration

| Name          | Class                    | Status     | API                              |
|---------------|--------------------------|------------|----------------------------------|
| `pexels`      | `PexelsProvider`         | ✅ Active   | Pexels Video API                 |
| `pixabay`     | `PixabayProvider`        | 🔌 Stub    | pixabay.com/api/videos/          |
| `nasa`        | `NasaMediaProvider`      | 🔌 Stub    | images-api.nasa.gov              |
| `wikimedia`   | `WikimediaCommonsProvider` | 🔌 Stub  | commons.wikimedia.org/w/api.php  |

## Routing Table

Category priority lists are defined in `configs/providers.yaml`:

```yaml
asset_routing:
  routes:
    Space:      [nasa, pixabay, pexels]
    History:    [wikimedia, pixabay, pexels]
    Science:    [nasa, pixabay, pexels]
    Nature:     [pixabay, pexels]
    Technology: [pixabay, pexels]
    Finance:    [pixabay, pexels]
    General:    [pixabay, pexels]
```

Providers are tried left-to-right.  The first provider that returns
non-empty results wins.

## Adding a New Provider

Adding a new provider requires **zero changes** to the orchestrator:

1. **Implement the `AssetProvider` interface:**

   ```python
   from src.providers.asset_provider import AssetProvider

   class MyProvider(AssetProvider):
       def search(self, query, **kwargs):
           # Call your API, return list of asset dicts
           ...

       def download(self, url, output_path):
           # Download from url to output_path
           ...
   ```

2. **Register it in `configs/providers.yaml`:**

   ```yaml
   asset_routing:
     routes:
       Science: [my_provider, nasa, pixabay, pexels]
   ```

3. **Instantiate it in `AssetRouter._default_providers()`:**

   ```python
   return {
       "pexels": AssetLibrary(provider=PexelsProvider()),
       "my_provider": MyProvider(),
       ...
   }
   ```

4. **Optionally wrap in `AssetLibrary`** for automatic local caching:

   ```python
   "my_provider": AssetLibrary(provider=MyProvider())
   ```

The orchestrator never directly instantiates providers — it calls
`AssetRouter.for_topic(topic)` and uses `router.search()` /
`router.download()`.

## Usage

```python
from src.assets import AssetRouter

# Create a topic-aware router
router = AssetRouter.for_topic("The Fermi Paradox")

# Search (tries NASA, Pixabay, Pexels in order)
results = router.search("milky way galaxy", target_duration=10)

# Download using the provider that returned results
if results:
    url = results[0]["video_files"][0]["link"]
    router.download(url, "cache/video/scene_1.mp4")
```

## Topic Categories

Keyword definitions are in `configs/providers.yaml` under
`asset_routing.keywords`.  Built-in categories:

| Category     | Example Keywords                                  |
|--------------|---------------------------------------------------|
| Space        | space, astronomy, planet, galaxy, nasa, rocket    |
| History      | history, ancient, empire, medieval, civilization   |
| Science      | science, physics, chemistry, dna, research         |
| Technology   | technology, computer, ai, software, robot          |
| Nature       | nature, animal, wildlife, forest, ocean            |
| Finance      | finance, money, economy, stock, investment         |
| General      | *(fallback — no keywords)*                         |

The classifier uses **keyword overlap scoring**: each keyword that appears
in the (lowercased) topic string adds one point.  The category with the
highest score wins.  Ties are broken alphabetically for determinism.

## Future Provider Ideas

- **Manim** — Programmatic math animations
- **Internet Archive** — Archive.org video search
- **OpenClipArt** — CC-licensed vector graphics
- **DeepAI** — AI-generated images/video
- **Stability AI** — Text-to-video generation
- **Local file system** — Reuse manually curated assets

# Avar Wordforms

Инструмент сборки и агрегации **словоформ** аварского языка.

> **Этот репозиторий не хранит данные.** Он только описывает логику сборки.
> Все исходные данные берутся при сборке из реестра **[sources.avar.me](https://sources.avar.me)**
> (единый источник правды экосистемы avar.me). Репозиторий ничего не добавляет от себя
> и не коммитит данные: на выходе — артефакты (CSV) и статический сайт. Любая правка
> исходников делается в `sources`, здесь — только код агрегации.

В git хранятся **только**: код (`avarforms/`, `build.sh`), конфигурация
(`config/sources.json`, ручные уточнения в `mappings/`) и статические файлы сайта
(`docs/*.html`, `*.js`, `*.css`, `docs/CNAME`). Всё сгенерированное (`output/`, `docs/data/`)
в `.gitignore` и собирается заново.

## Быстрый старт

```bash
./build.sh
```

Собирает (всё — генерируемое, не коммитится):

- `output/wordforms.csv` — агрегированный список словоформ
- `output/lemma_frequencies.csv` — **частотность по леммам** (`lemma,count`, по убыванию):
  суммарное число вхождений всех форм леммы по всем источникам. Главный артефакт для
  орфографа. Публикуется на сайте: `forms.avar.me/data/lemma_frequencies.csv`.
- `output/stats.json` / `output/stats.txt` — статистика сборки
- `docs/data/` — данные для сайта (поиск, статистика, скачивание)

Требования: Python 3.10+, без внешних зависимостей. Нужен интернет — источники качаются с sources.avar.me.

## Сайт и публикация

Сайт **forms.avar.me** разворачивается через GitHub Actions
(`.github/workflows/deploy.yml`): на каждый push в `main` workflow запускает `./build.sh`
(качает текущие источники → генерирует `docs/data/`) и публикует `docs/` на GitHub Pages.
Поэтому сайт всегда отражает **актуальные** данные sources.avar.me — отдельно пересобирать
вручную и коммитить данные не нужно.

- **Поиск** — `docs/index.html`: search-suggest, 10 случайных словоформ на главной
- **Статистика** — `docs/stats.html`: графики и цифры
- Скачивание — ссылка на `data/lemma_frequencies.csv` в футере

## Формат CSV

| Колонка | Описание |
|---------|----------|
| `wordform` | Словоформа |
| `lemma` | Лемма / базовое слово (может быть пустым) |
| `relation` | Тип связи: падеж, масдар, деепричастие и т.д. |
| `pos` | Часть речи словоформы |
| `source` | Название источника |
| `count` | Сколько раз встретилось при сборке |

Пример:

```csv
wordform,lemma,relation,pos,source,count
квачан,квачазе,деепричастие,глагол,AV-RU словарь Гимбатова,22
```

Если слово или связь не удалось определить — поле остаётся пустым.

## Структура проекта

```
avar/forms/
├── build.sh                    # Мастер-скрипт сборки
├── config/
│   └── sources.json            # Какие источники качать (URL) и чем извлекать
├── mappings/                   # Ручные уточнения маппинга (конфиг, не данные)
│   └── gimbatov.overrides.json
├── avarforms/                  # Python-фреймворк
│   ├── core/                   # Модели, пайплайн, статистика
│   ├── sources/                # Экстракторы по источникам
│   └── cli.py
├── .github/workflows/          # CI: build.sh + деплой на forms.avar.me
├── docs/                        # Статический сайт (в git — только .html/.js/.css/CNAME)
│   └── data/                    # ← генерируется сборкой, в .gitignore
└── output/                      # Артефакты сборки (CSV, статистика) — в .gitignore
```

Данные (`*.jsonl`, `docs/data/`, `output/`) в репозитории **не хранятся** — качаются и
собираются на лету.

## Источники

Исходные данные берутся из реестра **[sources.avar.me](https://sources.avar.me)** —
источника правды для всей экосистемы avar.me. При каждой сборке `av-ru.jsonl`
скачивается заново (без локального кэша), поэтому интернет обязателен.

Источники описываются в `config/sources.json`:

```json
{
  "id": "gimbatov",
  "name": "AV-RU словарь Гимбатова",
  "enabled": true,
  "module": "avarforms.sources.gimbatov",
  "class": "GimbatovExtractor",
  "config": {
    "url": "https://sources.avar.me/data/av-ru.jsonl"
  }
}
```

Для офлайн-сборки вместо `url` можно указать локальный `path`
(относительно корня проекта).

### Базовый источник и вторичные

- **av-ru** (`GimbatovExtractor`) — базовый: даёт **леммы** (заголовки) и формы.
- **ru-av, en-av, Тарас Бульба** (`avarforms.sources.mapped`) — вторичные: дают
  **только словоформы**, которые мапятся на уже имеющиеся леммы av-ru. Новых лемм
  не вводят. Берётся только аварский текст (ru-av: переводы `text` + `comment` +
  `examples.av`; en-av: поле `avar`; ТБ: `av`). Каждый источник указывает
  `index_source` — URL av-ru, по которому строится общий индекс лемм (кэшируется,
  собирается один раз).

  Маппинг вторичного токена принимается, если это **точный** заголовок/форма, либо
  фаззи-совпадение по основе, **но только если токен оканчивается на аварское
  словоизменительное окончание** — так аварские формы (`наслуялъе→наслу`) проходят,
  а иностранные слова, случайно совпавшие по основе с заимствованием
  (`расшить`, `самолет`), отбрасываются.

### AV-RU словарь Гимбатова

Экстрактор `GimbatovExtractor` извлекает словоформы из пяти подисточников:

| Подисточник | Описание | Качество |
|-------------|----------|----------|
| `explicit_relation` | Записи с явной связью (`masdarfrom`, `pluralfor`, `genitivefrom`, `deverbfrom` …) | Высокое |
| `headword` | Заголовок статьи → само на себя (`form`: инфинитив, именительный …) | Высокое |
| `forms` | Парадигмы из поля `forms` | Высокое (лемма известна, падеж часто нет) |
| `gender_forms` | Родовые формы | Высокое |
| `examples` | **Все** токены из примеров (`av`); маппинг — по индексу и контексту статьи, иначе lemma/relation пустые | Смешанное |

Правила извлечения зафиксированы в `.cursor/rules/wordform-extraction.mdc`: без хардкодов под отдельные слова, каждый токен из `av` попадает в корпус.

Поддерживаемые ключи связи:

- `masdarfrom`, `masdarforceto` → масдар
- `pluralfor` → множественное число
- `genitivefrom`, `dativefrom`, `locativefrom`, `ablativefrom`, `ergativefrom` → падежи
- `participlefrom` → причастие
- `deverbfrom` → деепричастие
- `forceto` → понудительная форма

## Добавление нового источника

1. Залейте данные в реестр [sources.avar.me](https://sources.avar.me) (или используйте локальный `path` для офлайн-данных)
2. Создайте экстрактор в `avarforms/sources/my_source.py`:

```python
from typing import Iterator
from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord

class MySourceExtractor(SourceExtractor):
    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        # yield WordFormRecord(
        #     wordform="...",
        #     lemma="...",
        #     relation="...",
        #     pos="...",
        #     source=self.source_name,
        #     subsource="...",
        # )
        ...
```

3. Зарегистрируйте в `config/sources.json`
4. При необходимости добавьте файл маппинга в `mappings/` и укажите его в секции `"mappings"`

5. Запустите `./build.sh`

## Улучшение маппинга

Файлы в `mappings/` позволяют вручную уточнять связи словоформа → лемма. Формат:

```json
{
  "description": "Ручные уточнения",
  "wordforms": {
    "квачан": {
      "lemma": "квачазе",
      "relation": "деепричастие",
      "pos": "глагол"
    },
    "простаяформа": "лемма"
  }
}
```

Маппинги применяются поверх автоматического извлечения и имеют приоритет.

Добавьте путь к файлу в `config/sources.json`:

```json
"mappings": [
  "mappings/gimbatov.overrides.json",
  "mappings/my_new_maps.json"
]
```

## Статистика

После сборки смотрите `output/stats.txt`:

- количество записей по источникам и подисточникам
- сколько записей без леммы / связи / части речи
- топ лемм, словоформ и типов связей
- «странные» записи (аномалии для ручной проверки)

## Разработка

```bash
export PYTHONPATH=.
python3 -m avarforms.cli
python3 -m avarforms.cli --root /path/to/project
```

Установка как пакет (опционально):

```bash
pip install -e .
avarforms-build
```

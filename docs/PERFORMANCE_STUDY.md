# دراسة أداء OneShelf: الكفرات، قائمة الشابترات، وفتح المحتوى

> **النطاق:** دراسة وتحليل فقط، بدون أي تعديل على الكود.
> **الريبوهات:** `IPurplel/OneShelf` (commit `8a31c19`، 2026-11-08) و`IPurplel/OneShelf-Adapters` (commit `2824235`، 2026-10-29).
> **ملاحظة على الاسم:** الريبو اسمه OneShelf وليس OnShelf. كل المراجع هنا إلى OneShelf.

## اصطلاحات التقرير

- **[مُقاس]**: رقم طلع من تشغيل فعلي لكود المشروع نفسه على بيئة الدراسة. السكربتات مذكورة في الملحق (أ).
- **[من الكود]**: استنتاج مباشر من قراءة الكود، أو حساب من ثوابته (مثلاً `60 / requests_per_minute`).
- **[استنتاج]**: يعتمد على سلوك معروف لطرف خارجي (المتصفح، SQLite، Pillow) ولم أقِسه هنا.
- مراجع الأسطر بصيغة `path:line`، ومساراتها نسبية لجذر كل ريبو. ملفات ريبو الأدابترات تبدأ بـ `adapters/…`.

## حدود الدراسة (بصراحة)

- **ما قِسته:** شغّلت الحاكم الحقيقي `TrafficGovernor` مع زمن شبكة محاكى. وقِست `CatalogTrust.refresh` و`_units()` على SQLite حقيقية بالمخطط الكامل (كل الـ migrations)، و`_validate_image`، والـ `RecipeRuntime` على fixtures الأدابترات (538 حالة)، وبناء الواجهة (`vite build`).
- **ما ما قدرت أقيسه:**
  - **التطبيق الكامل ضد المصادر الحقيقية.** بيئة الدراسة تمنع الوصول لمواقع المصادر (مسموح فقط لسجلات الحزم)، وPlaywright غير مثبت. لذلك ما فيه أي رقم لزمن شبكة حقيقي لموقع، وكل زمن شبكة في المحاكاة افتراضي ومذكور بجانبه.
  - **قياس المتصفح** (LCP، الـ jank، الذاكرة). ما فيه جهاز ولا متصفح حقيقي مع بيانات حقيقية.
- **صور الاختبار** في قياس فك الترميز ضوضاء عشوائية، وهي أسوأ حالة للضغط، فأحجام الملفات أكبر من الحقيقة. الأزمنة تعطي ترتيب الحجم، مو قيمة دقيقة لصورة حقيقية.
- **الجهاز:** 2 vCPU x86_64، وPython 3.13.

---

## 1. الملخص التنفيذي

### أهم 5 أسباب للبطء

1. **حد معدّل الطلبات لكل مصدر يُطبّق على كل طلب، حتى صور الـ CDN والكفرات.**
   - 93 من 114 أدابتر تعلن `requests_per_minute: 20` و`concurrency: 1`، وهذا هو القالب الافتراضي في `templates/basic-source/source.yaml`. **[من الكود]**
   - الحاكم يفرض فاصل `60/rpm` = **3 ثواني** بين أي طلبين لنفس المصدر (`backend/oneshelf/net/governor.py:111` و`:208`). المفتاح هو `plugin_id` وليس الـ host (`backend/oneshelf/sources/fetcher.py:54`).
   - النتيجة: شابتر Webtoon من 40 صورة يحتاج **117 ثانية على الأقل** للتحميل البارد **[من الكود]**، و6 صفحات أخذت **15.2 ثانية** في المحاكاة **[مُقاس]**.
2. **سعة HTTP العامة 4 طلبات فقط للتطبيق كله، والخلفية تأخذ منها 3.**
   - المصدر: `backend/oneshelf/settings/defaults.py:47` و`governor.py:170`. **[من الكود]**
   - كل الكفرات (`Priority.READ_AHEAD`)، والـ prefetch للصفحات، والـ Follow، والتنزيلات تتنافس على 3 خانات.
   - 60 كفر من 6 مصادر أخذت **6.0 ثانية**، ومع سعة 16 أخذت **1.5 ثانية**. **[مُقاس]**
3. **مسار الكفرات بدون كاش في السيرفر، وبدون تصغير، وأحياناً يشغّل recipe كامل لكل بطاقة.**
   - وضع `listing_key` يجلب صفحة `work` كاملة ثم الصورة، أي طلبين لكل كفر (`backend/oneshelf/api/covers.py:114` ثم `:130`).
   - 23 من 34 recipe بحث في الأدابترات المجتمعية، و`mangadex` الرسمي، ما تعطي `cover_url`. **[من الكود]**
   - النتيجة مع 20 rpm: حوالي **6 ثواني لكل كفر لكل مصدر**. **[من الكود]**
4. **سلسلة طلبات متتابعة (waterfall) قبل أول صفحة، وتتكرر مع كل شابتر.**
   - الترتيب: `context`، ثم `works/{id}` (الكتالوج كامل)، ثم `pages` (طلب شبكة للمصدر)، ثم الصورة. و`works/{id}` نفسه يُطلب مرتين (`frontend/src/features/reader/ReadRoute.tsx:24,41`، `ReaderScreen.tsx:91`).
   - قائمة الصفحات تعيش في الذاكرة 30 دقيقة فقط. بعدها، أو بعد إعادة تشغيل، لازم طلب شبكة جديد حتى لو الصفحات نفسها في الكاش (`backend/oneshelf/reader/service.py:316`). **[من الكود]**
5. **عمل CPU وكتابات SQLite متزامنة على event loop الوحيد.**
   - فك ترميز كامل بـ Pillow لكل كفر وكل صفحة: **9 إلى 350 ملي ثانية للصورة** **[مُقاس]**.
   - مقارنة O(n²) في تحديث الكتالوج: **1.47 ثانية** لكتالوج 6000 شابتر داخل `BEGIN IMMEDIATE`، يعني السيرفر كله متجمد **[مُقاس]**.
   - كتابة health signal بـ `synchronous=FULL` بعد كل تشغيل recipe.

### أكبر 5 تحسينات متوقعة الأثر

| # | التحسين | الأثر | الجهد |
|---|---|---|---|
| 1 | فصل ميزانية طلبات الموارد (صور الـ CDN) عن ميزانية صفحات المصدر، وتطبيق الحد لكل host | عالي جداً | M (Core وعقد اختياري) |
| 2 | رفع سعة HTTP العامة (مثلاً 12 إلى 16) وحجز خانات للقارئ | عالي | S |
| 3 | كاش كفرات دائم في السيرفر، مصغّر لحجم العرض، مع dedup وإلغاء عند انقطاع العميل، وحفظ نتيجة `listing_key` | عالي | M |
| 4 | endpoint واحد لفتح القارئ، مع stale-while-revalidate لقائمة الصفحات من `ReaderCache`، و prefetch مبكر للشابتر التالي | عالي | M |
| 5 | نقل الـ CPU والـ I/O المتزامن خارج event loop (`asyncio.to_thread`)، وإصلاح O(n²)، وتجميع الكتابات | متوسط إلى عالي (يخفف التجمد تحت الحمل) | S إلى M |

---

## 2. المرحلة 1: الفهم

### 2.1 الـ Stack

| الطبقة | OneShelf (التطبيق) | OneShelf-Adapters |
|---|---|---|
| اللغة | Python ≥3.12 (backend)، TypeScript (frontend) | YAML تصريحي، بدون أي كود تنفيذي (`docs/plugins.md` §1)، وأدوات Python للـ CI |
| الفريموورك | FastAPI وUvicorn (`backend/pyproject.toml`)، React 19 وVite 7 وreact-router 7 (`frontend/package.json`) | يُبنى ويُختبر بأداة Core المثبتة (`tooling/oneshelf-core-ref.txt`) |
| الشبكة | aiohttp (`backend/oneshelf/net/http.py`)، وcurl_cffi لـ NoorBook (`net/ech.py`)، وPlaywright للـ browser fetch (`net/browser.py`) | لا يوجد. الأدابتر يصف الطلب فقط |
| الـ parsing | scrapling/lxml Selector، وjsonpath داخلي، وRE2، وnh3 للنص | — |
| الصور | Pillow (تحقق)، وresvg لصور SVG في worker منفصل (`reader/page_image.py`)، و`<img>` بالمتصفح | — |
| التخزين | SQLite بـ WAL و`synchronous=FULL` (`db/connection.py:29-30`)، وملف `cache.db` منفصل لـ ReaderCache وDiscoveryCache، وblobs على القرص | الحزم `.osp` (ZIP) في الـ Registry |
| إدارة الحالة (واجهة) | `useState`/`useEffect`، وhook بسيط `useResource` (`frontend/src/api/useApi.ts`)، بدون مكتبة كاش (لا React Query ولا SWR)، وSSE `/api/events` | — |
| التوازي | asyncio بـ event loop واحد، و`TrafficGovernor` لكل طلب صادر، و`ThreadedResolver` للـ DNS | `rate_limit` و`timeouts` في `source.yaml` |

### 2.2 العقد بين التطبيق والأدابتر

- **الحزمة:** `manifest.yaml` و`source.yaml` و`recipes/<capability>.yaml` و`tests/` (`docs/plugins.md` §1-4).
- **القدرات:** `search`، `work`، `catalog`، `reader`، `downloads`، `latest` وغيرها.
- **الطلب:** Core يرسم الـ URL من القالب، والأدابتر لا يملك أي client.
  - `inputs`: `query`، `page`، `offset`، `cursor`، `listing_key`، `unit_key`، `url`، `language`.
  - `request`: `url`، `method`، `headers`، `form`، و`fetch: http|browser`، و`auth`.
- **الاستخراج:** `extract.items` و`fields` بأسماء ثابتة لكل قدرة، و`pagination` من أحد الأنماط: `none`، `page_number`، `offset`، `next_link`.
- **ما يرجع:** Core يحوّل الحقول إلى dataclasses (`backend/oneshelf/plugins/results.py`):
  - `Listing` (يحمل `cover_url`)
  - `UnitDescriptor` (الشابتر)
  - `ResourceDescriptor` (صفحة صورة `url`، أو نص `html` من API 1.2)
  - وتُغلّف بـ `ListResult(entries, complete, evidence)`.
- **سياسة الشبكة:**
  - `network.domains` و`cdn_domains` في الـ manifest.
  - `rate_limit {requests_per_minute (1..600, default 60), concurrency (1..4, default 2)}` و`timeouts` في `source.yaml` (`backend/oneshelf/plugins/schema.py:136-143`).
  - `resource_headers` في الـ recipe، مثل Referer لـ Webtoon (`adapters/official/oneshelf.webtoon/recipes/reader.yaml:16`).
- **ملاحظة مهمة للأداء:** الـ `rate_limit` **واحد للمصدر كله**. العقد ما يفرّق بين صفحة HTML للمصدر وصورة على CDN.

### 2.3 خريطة المسارات الثلاثة

#### (أ) الكفرات (Covers)

```
WorkCard (frontend/src/components/WorkCard.tsx:51-66)  IntersectionObserver rootMargin 240px
  └─ <img src="/api/covers?source=…&url=…">  أو  "?source=…&listing_key=…&alt_…"   (:82)
      │  (مسار cover_url يصنعه الخادم: backend/oneshelf/search/presentation.py:15 cover_path / :22 cover_lookup_path
      │   ويُختار في api/discovery.py:45-52 عند غياب cover_url في نتيجة البحث)
      ▼
GET /api/covers  (backend/oneshelf/api/covers.py:76)
  ├─ وضع url:          load_active → _image_response (:97 → :45)
  └─ وضع listing_key:  لكل مرشّح حتى 5 (:102):
         source_service.run(work recipe, Priority.READ_AHEAD)  (:114)   ← طلب صفحة/API كامل
         ثم _image_response(found_url)  (:130)
_image_response:
  SourceService.fetch_resource (sources/service.py:300)
    → SourceFetcher.request (sources/fetcher.py:42)
      → governor.acquire(plugin_id, READ_AHEAD)  (fetcher.py:54; governor.py:170 السعة، :208 الفاصل)
      → HttpClient.fetch (net/http.py:153)  aiohttp, redirect يدوي، body كامل بالذاكرة
  → detect_image_suffix + _validate_image (covers.py:70-71 → integrity/validators.py:133-150: verify + load كامل)
  → Response(bytes كما هي) + Cache-Control private max-age 7d / 1d  (covers.py:34-35)
المتصفح: يفك الصورة ويعرضها فوق CoverPlaceholder
```

#### (ب) قائمة الشابترات (Chapters)

```
WorkScreen (frontend/src/features/work/WorkScreen.tsx:70)  useResource('/api/works/{id}')
  ▼
GET /api/works/{id}  (backend/oneshelf/api/works.py:146)  ← من قاعدة البيانات فقط (local-first)
  _tracks (:30)  _units (:55: units + reading_state JOIN، release_events، assets، آخر download_job لكل وحدة)
  work_cover (search/presentation.py:50)
  ▼ إذا units فارغة (أول فتح) → WorkScreen.tsx:105-114
POST /api/tracks/{id}/catalog/refresh  (backend/oneshelf/api/discovery.py:336)
  SourceService.run('catalog')  (sources/service.py:237)
    RecipeRuntime._run_list  (plugins/runtime.py:442)  ← حلقة صفحات متسلسلة (:460)
      كل صفحة: governor → aiohttp → json.loads / lxml Selector (:329/:339) → استخراج الحقول
    _record → record_signal (sources/service.py:148-149 → sources/health.py)  كتابة SQLite
  CatalogTrust.refresh  (catalog/trust.py:81)  BEGIN IMMEDIATE: snapshot + snapshot_units + مقارنة + _materialize (:183)
  ▼
WorkScreen: reload() → GET /api/works/{id} مرة ثانية → units.map(...) كامل (WorkScreen.tsx:485)
(المسار من نتيجة بحث: POST /api/listings/open (discovery.py:273) يشغّل work ثم catalog بالتتابع :287-288)
```

#### (ج) فتح المحتوى (Reader)

```
Link → /read/{unitId}?work&track
ReadRoute (frontend/src/features/reader/ReadRoute.tsx:20)  key يتغير مع unitId → إعادة تركيب كاملة لكل شابتر
  1) GET /api/reader/units/{id}/context  (:24)  → api/library.py:431 → reader/service.py:152
  2) GET /api/works/{workId}?track_id      (:41)  ← الكتالوج كامل، ينتظر قبل أي شيء
  3) ReaderScreen يركّب ويطلب بالتوازي (ReaderScreen.tsx:90-93):
       /pages, /api/works/{work} (مكرر), /alternatives, /reader/settings, و/progress (useProgress.ts:49)
     GET /pages → api/library.py:360 → ReaderService.pages (reader/service.py:243)
        محلي CBZ: يفتح ZIP ويرتب الأسماء
        أونلاين: _online_descriptors (:274) → ذاكرة 30د (:316) وإلا → SourceService.run('reader', READER) (:320)
  4) <img src=/api/reader/units/{id}/pages/{n}> (ReaderScreen.tsx:745-752)
     GET → api/library.py:384 → ReaderService.page (reader/service.py:342)
        CBZ محلي: _archive_pages (فتح + ترتيب) ثم archive.read  (:349-353)
        كاش: ReaderCache.get (reader/cache.py:71) قراءة ملف + UPDATE last_used_at
        أونلاين: dedup in-flight (:370-390) → _fetch_online_page (:411) → fetch_resource (governor!)
                 → normalize_page_image (SVG فقط) → _validate_image (فك كامل) → cache.put (+evict SUM)
     الصفحات التالية: PagePreloads (pagePreloads.ts) concurrency 3، ?prefetch=1 → Priority.READ_AHEAD
     الشابتر التالي: warmNextUnit عند آخر صفحتين + 1.2 ث (ReaderScreen.tsx:514-524, :953)
نص (API 1.2): BookReader → GET /reader/units/{id}/text (api/library.py:462) → ReaderService.text (reader/service.py:220)
PDF/EPUB: BookReader يجلب الملف كامل arrayBuffer (BookReader.tsx:84-90)؛ pdf.js مع disableRange (PdfView.tsx:141)
التقدم: debounce 1200ms (useProgress.ts:7) → POST /progress → reader/service.py:_write (transaction واحدة)
```

---

## 3. المرحلة 2: التشخيص (جداول المشاكل)

### 3.1 الكفرات

| المشكلة | الموقع (ملف:سطر) | الدليل | الأثر المتوقع | الجهد | الحل المقترح |
|---|---|---|---|---|---|
| الكفرات تخضع لنفس فاصل المصدر (3 ث عند 20 rpm) لأن الحاكم يحسب بـ `plugin_id` حتى لو الصورة على CDN | `backend/oneshelf/sources/fetcher.py:54`، `net/governor.py:111,208`، `OneShelf-Adapters/templates/basic-source/source.yaml` | **[مُقاس]** 6 كفرات من مصدر واحد: آخرها عند 15.2 ث. **[من الكود]** 93 من 114 أدابتر بـ 20 rpm و`c1` | عالي | M | ميزانية منفصلة لطلبات الموارد. انظر §5 (أ) |
| سعة عامة 4، والخلفية (`READ_AHEAD`، وهي أولوية الكفرات) تأخذ 3 فقط لكل المصادر | `backend/oneshelf/settings/defaults.py:47`، `net/governor.py:170`، `api/covers.py:57` | **[مُقاس]** 60 كفر من 6 مصادر بزمن 300ms: 6.0 ث مقابل 1.5 ث بسعة 16 | عالي | S | رفع `http_concurrency` (12 إلى 16) وجعله إعداداً. خانات منفصلة لكل فئة (reader، كفرات، خلفية) |
| وضع `listing_key` يشغّل recipe `work` كامل لكل بطاقة (طلبان لكل كفر)، والنتيجة (`found_url`) لا تُحفظ | `backend/oneshelf/api/covers.py:102-133`، `api/discovery.py:45-52` | **[من الكود]** `cover_url` غائب في `adapters/official/oneshelf.mangadex/recipes/search.yaml` و23 من 34 recipe بحث مجتمعي | عالي (البحث والاكتشاف) | S إلى M | (1) بعد النجاح: `UPDATE source_listings SET cover_url = COALESCE(cover_url, ?)` كما يفعل `discovery.py:240-243`. (2) استخراج الكفر في recipe البحث، ويحتاج توسيع العقد §5 (ب) |
| لا كاش في السيرفر للكفرات. الاعتماد على HTTP cache للمتصفح فقط (`private`)، فمتصفح ثاني أو جهاز آخر أو مسح الكاش يعيد الجلب من المصدر | `backend/oneshelf/api/covers.py:34-35,73` | **[من الكود]** لا يوجد `put` أو `get` لأي كاش في `covers.py` | عالي | M | كاش على القرص (مثل `ReaderCache`) بمفتاح `sha256(source+url)`، وTTL طويل، وحد حجم مستقل |
| لا تصغير: تُرسل الصورة كما هي (حتى 4 MiB) لبطاقة عرضها نحو 120 إلى 200px | `backend/oneshelf/api/covers.py:27,73` | **[من الكود]** `MAX_COVER_BYTES = 4 MiB`، والـ body يُرجع بلا تحويل | متوسط (بيانات وذاكرة وdecode على الجوال) | M | توليد thumbnail (مثلاً 2 مقاس: 256 و512) بـ `Image.thumbnail` وحفظه WebP في الكاش. يتم في thread، و`img.draft()` لـ JPEG يسرّع التصغير |
| فك ترميز كامل (`verify` ثم `load`) على event loop لكل كفر | `backend/oneshelf/api/covers.py:71` → `integrity/validators.py:141-144` | **[مُقاس]** كفر 800×1200: JPEG 8.7 ms، WebP 46 ms | متوسط | S | `await asyncio.to_thread(_validate_image, …)`. أو الاكتفاء بـ `verify()` وحده للكفرات، فالتحقق الكامل يحصل عند صنع الـ thumbnail |
| لا dedup لطلبات متزامنة لنفس الكفر (Home وShelf وHero معاً)، بعكس صفحات القارئ | `backend/oneshelf/api/covers.py` (لا يوجد) مقابل `reader/service.py:370-390` | **[من الكود]** | منخفض إلى متوسط | S | خريطة in-flight بالمفتاح نفسه كما في `_page_fetches` |
| لا إلغاء عند ابتعاد البطاقة أو انقطاع الطلب. الطلب يستمر ويحجز خانة governor | `frontend/src/components/WorkCard.tsx:58-63` (`observer.disconnect` بعد أول ظهور)، `api/covers.py` (لا `is_disconnected`) | **[من الكود]** صفحات القارئ تفعلها (`api/library.py:388-400`) والكفرات لا | متوسط (تمرير سريع في البحث) | S | نفس نمط `request.is_disconnected()` في الكفرات |
| `fetchPriority="high"` على كل كفر مع `loading="lazy"` | `frontend/src/components/WorkCard.tsx:82` | **[استنتاج]** كل الكفرات high = لا أولوية فعلياً، وتنافس طلبات JSON | منخفض | S | `high` فقط لأول صف أو للـ Hero، والباقي `auto` |
| لا prefetch لما بعد 240px | `frontend/src/components/WorkCard.tsx:63` | **[من الكود]** | منخفض | S | يكفي بعد إصلاح السعة والكاش. زيادة الهامش قبل ذلك تزيد الازدحام |
| headers والـ referer والـ redirects | `api/covers.py:51-54`، `net/http.py:127-142` | **[من الكود]** Referer من `resource_headers` موجود. الـ redirect يدوي مع فحص سياسة لكل hop، وكل hop يمر بنفس الـ lease | منخفض | — | سليم. لا تغيير |

### 3.2 قائمة الشابترات

| المشكلة | الموقع (ملف:سطر) | الدليل | الأثر المتوقع | الجهد | الحل المقترح |
|---|---|---|---|---|---|
| الـ pagination متسلسل، وكل صفحة تنتظر فاصل المعدّل | `backend/oneshelf/plugins/runtime.py:460-474` | **[من الكود]** Webtoon: `pageSize=30` و20 rpm، فـ 600 حلقة = 20 صفحة × 3 ث ≈ **57 ث على الأقل**. Tapas: `max_limit=20` و20 rpm، فـ 500 حلقة ≈ **72 ث**. MangaDex: 60 rpm، فـ 800 شابتر ≈ 7 ث | عالي (أول فتح) | M | (1) ميزانية أدق لكل مصدر (§5 أ). (2) لـ `offset`/`page_number` مع `stop_when: total_count`: بعد الصفحة الأولى تُعرف `total`، فتُطلب الباقية بالتوازي حتى `concurrency` (Core فقط). (3) عرض تدريجي: حفظ snapshot `incomplete` وعرضه أثناء الجلب، مع الحفاظ على قواعد الثقة |
| عند فتح نتيجة بحث: `work` ثم `catalog` بالتتابع رغم استقلالهما | `backend/oneshelf/api/discovery.py:287-288` | **[من الكود]** | متوسط (يوفر طلباً واحداً، أي 3 ث على 20 rpm) | S | `asyncio.gather(_open_details(...), _open_catalog(...))`. الحاكم يرتّبهما، والتوازي يفيد فقط مع `concurrency>1`، لكن على الأقل لا تُضاف معالجة details بعد الشبكة |
| مقارنة O(n²) في تحديث الكتالوج: `set(new_keys)` يُبنى داخل الحلقة | `backend/oneshelf/catalog/trust.py:98` | **[مُقاس]** 6000 شابتر: 1212 ms مقابل 0.37 ms لو بُني الـ set مرة. تحديث "unchanged" كامل: 1469 ms، 3000: 195 ms، 1000: 33 ms | متوسط إلى عالي (يجمّد السيرفر كله داخل `BEGIN IMMEDIATE`، ويتكرر مع الـ Follow) | S | `new_set = set(new_keys)` قبل الحلقة |
| `_materialize`: `execute` لكل وحدة، و`NOT IN (?,?,…)` بكل المفاتيح | `backend/oneshelf/catalog/trust.py:186-202` | **[مُقاس]** أول refresh: 6000 = 175 ms | منخفض إلى متوسط | S | `executemany`، وجدول مؤقت أو `json_each` بدل قائمة المعاملات |
| الـ parsing وjsonpath والـ selectors وnh3 كلها على event loop | `backend/oneshelf/plugins/runtime.py:329,339,507` | **[مُقاس]** `3asq` catalog (171 KiB، 404 عنصر): 78.5 ms، و`chitanka` 35.8 ms، ومعظم الحالات أقل من 20 ms | منخفض إلى متوسط (يظهر تحت التوازي) | S | `await asyncio.to_thread(parse+extract)` للصفحات فوق حجم معيّن |
| لا stale-while-revalidate عند وجود وحدات: لا تحديث تلقائي عند الفتح، والتحديث على Follow كل 12 ساعة أو زر يدوي | `frontend/src/features/work/WorkScreen.tsx:105-114`، `settings/defaults.py:55` | **[من الكود]** العرض من DB فوري (جيد) لكن قد يكون قديماً | منخفض (للسرعة) ومتوسط (للحداثة) | S | تحديث بالخلفية إذا آخر `fetched_at` أقدم من X، وعرض "تم التحديث" دون حجب |
| القائمة تُرسم كاملة بلا virtualization، وكل حدث تنزيل يعيد جلب `/api/works/{id}` كاملاً ويعيد بناءها | `frontend/src/features/work/WorkScreen.tsx:76,485` | **[من الكود]** 1000+ `<li>` مع أزرار. التحديث مجمّع كل 800ms. **[استنتاج]** على الجوال يسبب jank أثناء "تنزيل الكل" | متوسط (كتالوجات طويلة) | M | قائمة افتراضية (مثل `@tanstack/react-virtual`)، و`React.memo` للصف، وتحديث جزئي من حدث `download.job` نفسه بدل إعادة الجلب |
| `_units()` استعلام فرعي مترابط لآخر job لكل وحدة، و`release_events` بلا index على `track_id` | `backend/oneshelf/api/works.py:62-64,74-77`، `db/schema/0008_follow.sql:31` | **[مُقاس]** `_units()` بلا jobs: 300 = 1.8 ms، 1000 = 4.6 ms، 3000 = 11.7 ms، 6000 = 29.1 ms. أداء مقبول. الاستعلام الفرعي لم يُقس مع jobs كثيرة | منخفض | S | index على `release_events(track_id, seen)` و`download_jobs(reading_unit_id, created_at)` |
| N+1 | `backend/oneshelf/library/shelf.py:93-149`، `search/presentation.py:72` | **[من الكود]** الـ shelf والكفرات مجمّعة (`_batch_entries`، `work_covers`). لا N+1 ظاهر في المسار | — | — | سليم |

### 3.3 فتح المحتوى (Reader)

| المشكلة | الموقع (ملف:سطر) | الدليل | الأثر المتوقع | الجهد | الحل المقترح |
|---|---|---|---|---|---|
| صفحات الصور على CDN تخضع لفاصل المصدر حتى بأولوية `READER` | `backend/oneshelf/reader/service.py:417` → `sources/fetcher.py:54` → `net/governor.py:208` | **[مُقاس]** 6 صفحات عند 20 rpm و`c1`: الأولى 0.15 ث، والأخيرة 15.2 ث. **[من الكود]** شابتر Webtoon من 40 صورة ≥117 ث. **[مُقاس]** بميزانية CDN 600 rpm و`c4`: 24 صفحة في 2.5 ث | **عالي جداً** | M | §5 (أ). وحتى بدون تغيير العقد: إعطاء الموارد ضمن `cdn_domains` فاصلاً أقصر في Core |
| الـ prefetch (`?prefetch=1` بأولوية `READ_AHEAD`) لا يأخذ الخانة الأخيرة، ويتنافس مع الكفرات والتنزيلات | `backend/oneshelf/api/library.py:388-390`، `reader/service.py:373`، `net/governor.py:170` | **[من الكود]** | متوسط | S | أولوية مستقلة `READER_PREFETCH` بين `READER` و`INTERACTIVE`، أو خانات محجوزة للقارئ |
| سلسلة الطلبات قبل أول صفحة: `context` ثم `works` (كتالوج كامل) ثم `pages` (شبكة المصدر) ثم الصورة. و`works` مكرر | `frontend/src/features/reader/ReadRoute.tsx:24,41`، `ReaderScreen.tsx:90-93` | **[من الكود]** 3 رحلات متتالية للسيرفر قبل طلب الصورة، والثانية تحمل الكتالوج كله | متوسط إلى عالي (على شبكة LAN أو بعيدة) | M | endpoint واحد `GET /api/reader/units/{id}/open` يرجع context والصفحات والتقدم والشابتر السابق والتالي فقط. يُطلب `pages` بالتوازي مع `context` |
| `ReadRoute` يعيد تركيب كل شيء مع كل شابتر (`key` يحتوي `unitId`)، فتتكرر السلسلة كاملة | `frontend/src/features/reader/ReadRoute.tsx:20` | **[من الكود]** | متوسط | S إلى M | الاحتفاظ ببيانات العمل (works) في كاش على مستوى التطبيق، أو `key` بدون unitId مع إعادة ضبط الحالة يدوياً (`ReaderScreen` يفعلها أصلاً) |
| قائمة الصفحات (descriptors) في الذاكرة 30 دقيقة فقط. بعدها طلب شبكة حتى لو الصور في `ReaderCache`، والقائمة المخزّنة في `reader_descriptors` لا تُستخدم إلا عند تعطّل المصدر | `backend/oneshelf/reader/service.py:40-41,293-311,316-320` | **[من الكود]** | عالي (إعادة فتح شابتر مقروء أونلاين) | S إلى M | stale-while-revalidate: إرجاع المخزّن فوراً، ثم تحديثه بالخلفية. منطق "الرابط انتهى" موجود أصلاً (`:422-440`) ويعالج الروابط الموقّعة |
| تسخين الشابتر التالي متأخر: آخر صفحتين ثم 1.2 ث، و3 صفحات فقط، وبأولوية `READER` (بدون `prefetch=1`) | `frontend/src/features/reader/ReaderScreen.tsx:514-524,953-966` | **[من الكود]** مع 3 ث لكل طلب لا يكفي الوقت لتجهيز التالي | متوسط | S | جلب descriptors التالي عند نحو 50%، والصفحات الأولى عند نحو 80% بـ `?prefetch=1` |
| Long Strip: الـ preload pool معطّل، والاعتماد على `loading="lazy"` للنافذة المركّبة | `frontend/src/features/reader/ReaderScreen.tsx:552-554` | **[من الكود]** | منخفض إلى متوسط | S | تفعيل band صغيرة في Long Strip أيضاً |
| فك ترميز كامل لكل صفحة أونلاين على event loop، والـ webp أبطأ بكثير | `backend/oneshelf/reader/service.py:451` → `integrity/validators.py:141-144` | **[مُقاس]** صفحة مانغا 1100×1600: JPEG 14.8 ms، WebP 97 ms. شريط 720×10000: JPEG 84 ms، WebP 353 ms | متوسط (يجمّد بقية الطلبات) | S | `asyncio.to_thread` |
| CBZ محلي: لكل صفحة يُفتح ZIP، وتُرتب كل الأسماء، وتتم القراءة على event loop | `backend/oneshelf/reader/service.py:349-353,211-214` | **[من الكود]** O(عدد الصفحات) لكل طلب | منخفض إلى متوسط | S | كاش LRU لقائمة الأسماء بـ `(path, mtime)`، والقراءة في thread |
| `ReaderCache.get` يكتب `UPDATE` لكل قراءة، و`evict()` ينفذ `SUM(size)` على كامل الجدول بعد كل `put` | `backend/oneshelf/reader/cache.py:82,102` | **[من الكود]** sqlite متزامن على event loop | منخفض | S | عدّاد حجم بالذاكرة، وتحديث `last_used_at` مجمّع أو باحتمال |
| PDF وEPUB: الملف كاملاً قبل أول صفحة (`disableRange`)، رغم أن السيرفر يدعم Range | `frontend/src/features/reader/BookReader.tsx:84-90`، `PdfView.tsx:141`، `api/library.py:457` | **[من الكود]** قرار أمني مقصود حسب التعليق | متوسط (ملفات كبيرة) | M | يُدرس: `range` لـ pdf.js داخل نفس الحماية، أو شاشة تقدّم بالحجم |
| النص أونلاين (API 1.2): لا يُحفظ في الكاش، ويُعقّم مرتين (runtime ثم `unit_sections`) | `backend/oneshelf/reader/service.py:220-240`، `plugins/runtime.py:507` | **[من الكود]** `Cache-Control: no-store` (`api/library.py:43`) | منخفض إلى متوسط | S | نفس stale-while-revalidate للـ descriptors، فالـ html موجود فيها |
| الأوفلاين: هل المحمّل يفتح بلا شبكة؟ | `backend/oneshelf/reader/service.py:243-247,342-353,220-226` | **[من الكود]** نعم. `cbz`/`text`/`epub`/`pdf` المحلي يُقرأ قبل أي سؤال للمصدر، وصفحات `local` بـ `max-age=604800` (`api/library.py:45`) | — | — | سليم |
| حفظ موضع القراءة | `frontend/src/features/reader/useProgress.ts:7,63-67`، `backend/oneshelf/reader/service.py:485-503` | **[من الكود]** debounce 1200ms، وكتابة متسلسلة. لكن `progress()` تقرأ ثم تكتب في transaction مع `synchronous=FULL` (fsync) على event loop | منخفض | S | كافٍ. يمكن نقل الكتابة لـ thread |

### 3.4 عام (للريبوين)

| المشكلة | الموقع (ملف:سطر) | الدليل | الأثر المتوقع | الجهد | الحل المقترح |
|---|---|---|---|---|---|
| قالب الأدابتر الافتراضي 20 rpm و`c1`، فصار هو الحد لـ 93 من 114 أدابتر بغض النظر عن قدرة المصدر | `OneShelf-Adapters/templates/basic-source/source.yaml`، `adapters/*/*/source.yaml` | **[من الكود]** التوزيع: 6 rpm ×7، و10 ×4، و12 ×1، و20 ×93، و30 ×8، و60 ×1. والتوازي: 1 ×112، و2 ×2 | عالي | S (سياسة) إلى M (مراجعة لكل مصدر) | مراجعة الحدود للمصادر الرسمية (API عامة مثل MangaDex تسمح بأكثر)، وفصل حد الموارد |
| HTTP/1.1 فقط من المتصفح، مع اتصالَي SSE دائمين يستهلكان من حد 6 اتصالات لكل host | `frontend/src/app/live.tsx:60`، `features/search/SearchScreen.tsx:103`، `deploy/nginx/oneshelf.conf.template:13` (`listen` بلا http2)، Uvicorn بلا HTTP/2 | **[استنتاج]** حد 6 اتصالات لكل host في HTTP/1.1 مشترك بين التبويبات. أثناء البحث يبقى 4 للكفرات والـ JSON | متوسط | S إلى M | HTTP/2 في nginx (يتطلب TLS للمتصفحات)، أو دمج SSE في قناة واحدة |
| aiohttp: `use_dns_cache=False` مع `ThreadedResolver` | `backend/oneshelf/net/http.py:101-102` | **[من الكود]** DNS لكل اتصال جديد (مقصود ضد DNS rebinding). keep-alive يخفف الأثر. `limit=16` لكل مصدر | منخفض | S | كاش DNS قصير داخل `PolicyResolver` مع إعادة الفحص (لا يفتح ثغرة لأن الفحص على العنوان المحفوظ) |
| HTTP/2 للمصادر | `backend/oneshelf/net/http.py` | **[من الكود]** aiohttp لا يدعم HTTP/2. الـ compression (`gzip`/`deflate`) افتراضي في aiohttp | منخفض | L | لا يستحق الآن، فالحد هو rate limit وليس البروتوكول |
| timeouts | `backend/oneshelf/plugins/schema.py:141-143`، `net/http.py:97` | **[من الكود]** `connect=10s` و`sock_read=30s` و`total=None`. صفحة بطيئة تحجز خانة governor (السعة 4) حتى 30 ث لكل قراءة | متوسط (مع سعة 4) | S | `total` معقول للصور، وتخفيض `read` للكفرات |
| retries | `backend/oneshelf/plugins/runtime.py:310-321`، `sources/fetcher.py:57-59` | **[من الكود]** لا retry تلقائي في القراءة أونلاين. 429 يضبط `retry_until`، و`DEFAULT_RETRY_AFTER=60` ث يوقف المصدر كله دقيقة | منخفض إلى متوسط | S | retry واحد مع jitter للأخطاء الشبكية العابرة في الصور |
| SQLite واحد مشترك (`check_same_thread=False`) وكل الاستعلامات متزامنة داخل `async def` | `backend/oneshelf/db/connection.py:21-31`، و`api/*.py` | **[من الكود]** `synchronous=FULL` يعني fsync لكل commit على event loop | متوسط تحت الحمل | M | `synchronous=NORMAL` مع WAL (آمن ضد الفساد، ويخسر آخر transaction عند انقطاع الكهرباء فقط، ويُقرر حسب سياسة المشروع)، ونقل الكتابات الثقيلة لـ thread |
| health signal لكل تشغيل recipe: 4 عبارات منها `DELETE … WHERE created_at < ?` بلا index (SCAN) | `backend/oneshelf/sources/service.py:148-149,275`، `sources/health.py:29-41` | **[مُقاس]** 0.40 ms وسيط مع 3000 صف، بخطة `SCAN source_health_signals`. صغير لكن fsync على قرص بطيء (NAS أو SD) قد يصل لعشرات الـ ms **[استنتاج]** | منخفض | S | index على `created_at`، وتنفيذ الحذف كل N مرة، وتجميع الإشارات |
| cold start: migrations، واستعادة التنزيلات، و`reconcile` (stat لكل asset)، وبناء الحزم المضمّنة، كلها قبل `yield` | `backend/oneshelf/api/app.py:244-306`، `storage/scanner.py:54-79`، `plugins/bundled.py:125-149` | **[مُقاس]** بناء وتحميل 9 حزم مضمّنة 106 ms، واستيراد الوحدات الأساسية 253 ms. **[من الكود]** `reconcile` يعمل `stat` لكل ملف محمّل في كل تشغيل، O(عدد الـ assets)، وهو المكلف على مكتبة كبيرة | منخفض (مكتبة صغيرة) ومتوسط (عشرات آلاف الملفات على NAS) | M | `reconcile` في الخلفية بعد الإقلاع، مع أن `/api/health` جاهز يعكس ذلك |
| حجم الواجهة: الحزمة الرئيسية 676 kB (210 kB gzip)، وpdf.js 434 kB محمّل كسولاً | `frontend/vite.config.ts`، `app/routes.tsx:10-18` | **[مُقاس]** `vite build`. التشغيل المباشر على 8420 بلا nginx: لا gzip (لا `GZipMiddleware`)، و`/assets` بلا `Cache-Control immutable` (`api/app.py:227`) | منخفض إلى متوسط (أول تحميل) | S | `GZipMiddleware` أو ضغط مسبق، و`immutable` لـ `/assets` في التطبيق نفسه، وفصل `motion` و`embla` |
| إعادة الرسم الزائدة | `frontend/src/features/reader/ReaderScreen.tsx:530-559`، `WorkScreen.tsx:485` | **[من الكود]** `rerenderPreloads` يعيد رسم القارئ كله مع كل صورة preload. `setLoaded(new Set(...))` لكل صفحة | منخفض إلى متوسط | S | فصل شريط الصفحات في مكوّن `memo`، وتخزين حالة preload خارج React (`useSyncExternalStore`) |
| delays مصطنعة | Core والأدابترات | **[من الكود]** لا يوجد `sleep` في المسارات الثلاثة. الانتظار كله من فاصل `min_interval` في الحاكم (حد معدّل وليس تأخيراً مصطنعاً). `asyncio.sleep(0.02)` فقط في انتظار slot الـ SVG (`reader/page_image.py:57`) | — | — | — |

### 3.5 ما هو جيد أصلاً (لا يُلمس)

- **صفحة العمل local-first:** `api/works.py:146` لا يلمس الشبكة.
- **الصفحات:** in-flight dedup، وإلغاء prefetch عند انقطاع العميل، و`promote` للأولوية (`reader/service.py:370-390`، `api/library.py:388-400`).
- **حماية الذاكرة في القارئ:** نافذة مركّبة محدودة في Long Strip، و`revokeObjectURL` (`pagePreloads.ts:24-29`).
- **الأوفلاين:** المحلي يُقرأ قبل الشبكة.
- **قاعدة البيانات:** الـ shelf والكفرات batched بلا N+1.
- **الواجهة:** routes وpdf.js كسولة.
- **الكفرات:** `IntersectionObserver` يمنع إغراق المصدر.

---

## 4. خطة التنفيذ مرتّبة حسب (الأثر ÷ الجهد)

### المرحلة A: Quick wins (أيام)

1. **رفع سعة الحاكم:** `DownloadDefaults.http_concurrency` من 4 إلى 12-16، وجعلها إعداداً (`settings/defaults.py:47`). لا يمس حدود المصادر، فكل مصدر ما زال مقيداً بـ `concurrency` و`rpm`.
2. **إصلاح O(n²):** `set(new_keys)` مرة واحدة (`catalog/trust.py:98`). سطر واحد يوفّر نحو 1.2 ث لكل 6000 شابتر.
3. **`asyncio.to_thread`** لـ `_validate_image` في `covers.py:71` و`reader/service.py:451`، و`archive.read` في `reader/service.py:353`.
4. **حفظ `cover_url` بعد نجاح وضع `listing_key`** في `source_listings` (`covers.py:125-132`). المرة الثانية تصير طلباً واحداً بدل اثنين.
5. **`asyncio.gather`** لـ `_open_details` و`_open_catalog` (`api/discovery.py:287-288`).
6. **إلغاء الكفر عند انقطاع العميل،** ودمج الطلبات المتزامنة (in-flight dedup) في `covers.py`.
7. **الواجهة:** إزالة طلب `works` المكرر في القارئ (تمرير `details` من `OpenUnit` إلى `ReaderScreen`)، وتسخين الشابتر التالي مبكراً بـ `?prefetch=1`.
8. **indexes:** `source_health_signals(created_at)`، و`release_events(track_id, seen)`، و`download_jobs(reading_unit_id, created_at)`.

### المرحلة B: تحسينات متوسطة (أسابيع)

1. **ميزانية موارد منفصلة في Core:** فاصل وتوازي مستقلان لطلبات `fetch_resource` إلى `cdn_domains`، مع إبقاء حد صفحات المصدر كما هو. يمكن البدء بقيمة Core افتراضية محافظة، ثم إتاحتها في العقد (§5 أ).
2. **كاش كفرات على القرص مع thumbnails** بمقاسين (WebP)، وإرجاع `ETag`.
3. **stale-while-revalidate لقائمة صفحات القارئ** من `ReaderCache.reader_descriptors`.
4. **endpoint `open` موحّد للقارئ،** وكاش بيانات العمل في الواجهة (أو React Query أو SWR).
5. **قائمة شابترات افتراضية (virtualized)،** وتحديث جزئي عند أحداث التنزيل.
6. **جلب صفحات الكتالوج بالتوازي** عند `total_count` المعروف (حتى `concurrency` المصدر)، وعرض تدريجي.
7. **أولويات وخانات منفصلة للقارئ** داخل الحاكم.

### المرحلة C: تغييرات معمارية

1. **العقد API 1.3:** `rate_limit.resources`، وقوالب بحقول العنصر (§5).
2. **HTTP/2 بين المتصفح والتطبيق** (TLS في nginx)، ودمج قنوات SSE.
3. **فصل CPU-bound بالكامل:** worker pool للـ parsing، وفك الصور، والـ thumbnails.
4. **`reconcile` في الخلفية** بعد الإقلاع، ومراجعة `synchronous=FULL`.

---

## 5. تغييرات مقترحة في عقد الأدابتر

| # | التغيير | الشكل المقترح | التوافق مع الأدابترات الحالية |
|---|---|---|---|
| أ | **حد معدّل منفصل للموارد (الصور وملفات CDN)** | `source.yaml`:<br>`rate_limit: {requests_per_minute: 20, concurrency: 1, resources: {requests_per_minute: 300, concurrency: 4}}`<br>ويُطبّق على `fetch_resource` و`stream` لعناوين ضمن `cdn_domains`، أو لكل الموارد | **متوافق للخلف:** غياب `resources` يعني السلوك الحالي، أو قيمة Core افتراضية محافظة لو قرر المالك ذلك. Core قديم يرفض الحزمة لأن `Strict` يمنع المفاتيح المجهولة (`schema.py:136`)، فيلزم `api: '1.3'` مع فحص لكل ميزة كما في 1.2 (`plugins.md` §2). يحتاج مراجعة: هل يسمح الـ CDN فعلاً بالمعدّل الأعلى؟ |
| ب | **قوالب تشير لحقول نفس العنصر** | `cover_url: {template: "https://uploads.mangadex.org/covers/{field:listing_key}/{cover_file}.256.jpg"}` مع `values` لكل عنصر، أو `item_values` | **متوافق:** ميزة جديدة اختيارية. حالياً `{item}` هو قيمة العنصر الخام فقط (`runtime.py:141-159`)، فلا يمكن بناء رابط الكفر في البحث من id واسم الملف معاً. يلزم `api: '1.3'` |
| ج | **(اختياري) تلميح حجم الكفر** | `cover_thumbnail_url` أو قالب حجم، لمصادر تقدم أحجاماً (`.256.jpg` في MangaDex) | **متوافق:** حقل اختياري. البديل في Core وحده هو التصغير (§3.1) |
| د | **(بدون تغيير عقد) تحسين بيانات الأدابترات نفسها** | إضافة `cover_url` لـ recipes البحث الـ 23 حيث ممكن. MangaDex: `includes[]=cover_art` في البحث (يحتاج ب). مراجعة `rate_limit` للرسمية | لا أثر على التوافق. إصدار جديد لكل أدابتر (`version` bump) |

> **ملاحظة:** جلب صفحات الكتالوج بالتوازي **لا يحتاج** تغيير عقد. يكفي Core مع `offset`/`page_number` و`total_count`، لكن فائدته محصورة بـ `concurrency` المصدر (1 لأغلب الأدابترات).

---

## 6. المخاطر والتنازلات

| التحسين | المخاطر والتنازلات |
|---|---|
| ميزانية موارد أعلى، أو رفع rpm | **خطر الحظر من المصدر أو CDN** (429، أو حظر IP)، ومخالفة سياسة المراجعة "No bypasses… rate limits" (`docs/review-policy.md:10`). يجب أن تكون القيم معلنة من الأدابتر وتخضع لمراجعة، لا رفعاً صامتاً. مع ذلك `Retry-After` يبقى محترماً (`fetcher.py:57-59`) |
| سعة HTTP عامة أعلى | ذاكرة أكثر (أجسام الردود بالذاكرة حتى 64 MiB في `fetch`، و`net/http.py:26`)، واتصالات أكثر، واستهلاك أكبر للبيانات والبطارية لو كان السيرفر على جهاز محمول |
| كاش كفرات وthumbnails | مساحة قرص (يلزم حد ووقت انتهاء)، وCPU للتصغير (يحصل مرة). كفر قديم لو غيّر المصدر الصورة بنفس الرابط (TTL يعالج ذلك) |
| stale-while-revalidate للـ descriptors | عرض قائمة صفحات قديمة (روابط موقّعة منتهية). المنطق الحالي للتجديد عند 403/404/410 يغطيها، مع زيادة طلب أحياناً. مصادر تحذف أو تعيد ترتيب الصفحات قد تظهر قديمة حتى ينتهي التحديث بالخلفية |
| prefetch مبكر للشابتر التالي | بيانات وطلبات على مصدر محدود لشابتر قد لا يُقرأ، ويستهلك من rate limit المصدر. لذلك يكون بأولوية خلفية وقابلاً للإلغاء (`leave` موجود) |
| `asyncio.to_thread` | threads إضافية، وPillow يحرر الـ GIL جزئياً. يلزم حد (semaphore) لمنع تضخم الذاكرة مع صور كبيرة متزامنة |
| `synchronous=NORMAL` | خسارة آخر transactions عند انقطاع الكهرباء (لا فساد مع WAL). يتعارض مع سياسة "FULL sync" المعلنة (Master §18)، والقرار للمالك |
| التحميل التدريجي للكتالوج | يجب ألا يكسر قواعد الثقة (`catalog/trust.py:1-6`): ما يُعرض أثناء الجلب يبقى `incomplete` ولا يغذي Follow أو Download Missing |
| virtualization | أثر على الوصولية (البحث بـ Ctrl+F، وقارئ الشاشة). يلزم تعامل مع `aria` و`scroll-restoration` |
| HTTP/2 وTLS على LAN | شهادات (self-signed أو local CA) وتعقيد للمستخدم |
| رفع `max_pages` أو التوازي في الكتالوج | عبء أعلى على المصدر في لحظة واحدة |

---

## 7. المرحلة 3: خطة القياس قبل وبعد

### 7.1 المؤشرات

| المؤشر | التعريف | الهدف المقترح (للنقاش) |
|---|---|---|
| **time-to-first-cover** | من ظهور البطاقة في الـ viewport إلى `onLoad` للـ `<img>` (أو للـ placeholder عند الفشل) | p50 < 500ms (كاش ساخن)، وp90 < 2s (بارد) |
| **time-to-all-visible-covers** | من رسم الشبكة إلى تحميل كل الكفرات الظاهرة | — |
| **chapter-list-load** | (أ) من الضغط على العمل إلى أول رسم لقائمة الشابترات من DB. (ب) من بدء `catalog/refresh` إلى اكتماله، مع عدد الصفحات المجلوبة | (أ) < 300ms، و(ب) حسب المصدر |
| **time-to-first-page** | من الضغط على الشابتر إلى `onLoad` لأول صورة (أو أول section نص) | محلي < 300ms، وكاش < 800ms، وأونلاين بارد يُقاس لكل مصدر |
| **time-to-next-chapter** | من "اقرأ التالي" إلى أول صفحة | قريب من الكاش الساخن |
| **governor wait** | زمن الانتظار داخل `governor.acquire` لكل طلب، حسب الأولوية والمصدر | — |
| **event-loop lag** | أقصى تأخر للـ loop كل ثانية | p99 < 50ms |

### 7.2 نقاط الـ instrumentation المحددة

**Backend (Python):**

1. **`net/governor.py` في `_wait` (:138):** سجّل `t_enqueue` وزمن الحصول على lease، مع `source` و`priority` و`kind`. وأضف عدادات `waiting` و`in_use` لكل مصدر إلى `snapshot()` (:119).
2. **`sources/fetcher.py:54-56`:** زمن الانتظار مقابل زمن الشبكة الفعلي، والحالة، والحجم.
3. **`plugins/runtime.py`:**
   - `_fetch_page` (:310): زمن الـ parse منفصلاً عن الشبكة.
   - `_run_list` (:442): عدد الصفحات و`stop_reason`.
4. **`reader/service.py`:** مصدر كل صفحة (`origin`: local، cache، online)، وزمن `_load_online_descriptors`، وزمن `_validate_image`.
5. **`api/covers.py`:** المسار (url أو listing_key)، وعدد المرشحين المجربين، والزمن الكلي.
6. **`catalog/trust.py:81`:** زمن `refresh` وعدد الوحدات.
7. **Middleware بسيط** يضيف `Server-Timing: governor;dur=…, net;dur=…, parse;dur=…, db;dur=…` لكل رد. يظهر مباشرة في DevTools.
8. **مراقب event-loop lag:** مهمة تنام 100ms وتقيس الانحراف، وتسجّل في `diagnostics`.

**Frontend (TypeScript):**

1. `performance.mark('cover:visible')` في `WorkCard.tsx:60`، و`performance.measure` في `onLoad` و`onError` (:83-85).
2. `performance.mark('work:click')` عند `Link`، و`measure` عند أول رسم لـ `units.map` (`WorkScreen.tsx:485`).
3. `reader:click` إلى `onLoad` لأول صفحة (`ReaderScreen.tsx:753`)، أو إلى `setHtml` في `BookReader`.
4. إرسال القياسات عبر `PerformanceObserver` إلى endpoint محلي (`/api/diagnostics/timings`) أو `console` في وضع التطوير.

### 7.3 الأدوات

- **Backend:** `py-spy record`/`top` لمعرفة أين يقضي الـ loop وقته، و`asyncio` debug mode (`PYTHONASYNCIODEBUG=1`، `loop.slow_callback_duration=0.05`)، و`EXPLAIN QUERY PLAN` لاستعلامات `works.py` و`health.py`.
- **مصدر تجريبي حتمي:** `backend/testsource` مع `ONESHELF_DEV_TEST_SOURCE=1` لقياس قبل وبعد بدون شبكة حقيقية، مع زمن استجابة ورد 429 قابلين للضبط.
- **Frontend:** Chrome DevTools (Performance وNetwork مع throttling "Fast 4G" وCPU 4x)، وLighthouse لـ cold load، وReact Profiler لإعادة الرسم في `WorkScreen` و`ReaderScreen`.
- **سكربتات الملحق (أ):** قابلة لإعادة التشغيل كـ regression benchmarks.

### 7.4 إجراء القياس

1. **سيناريوهات ثابتة:**
   - S1: بحث يُرجع 40 نتيجة من 3 مصادر.
   - S2: فتح عمل بـ 600 شابتر (Webtoon) لأول مرة، ثم مرة ثانية.
   - S3: فتح شابتر أونلاين 40 صورة بارد، ثم إعادة فتحه بعد 31 دقيقة.
   - S4: الانتقال للشابتر التالي.
   - S5: شابتر محمّل CBZ بلا شبكة.
2. **التكرار:** كل سيناريو 10 مرات، وتسجيل p50 وp90 والحد الأقصى، مع كاش بارد (مسح `reader-cache` وكاش المتصفح) ودافئ.
3. **قبل وبعد** كل خطوة من §4 بنفس الأجهزة والشبكة. وتسجيل عدد الطلبات للمصدر (من سجل الحاكم) للتأكد أن التسريع لم يأتِ من إغراق المصدر.

---

## ملحق (أ): القياسات الفعلية وطريقتها

كل السكربتات تستورد كود `backend/oneshelf` من الريبو كما هو، بدون أي تعديل عليه.

**1. الحاكم (`bench_governor.py`):** `TrafficGovernor` الحقيقي، مع `asyncio.sleep` بديلاً عن الشبكة.

```
reader pages, 1 src @20rpm c1, 6 pages, 150ms each   first=0.15s  median= 9.16s  last=15.17s
covers,       1 src @20rpm c1, 6 covers (READ_AHEAD)  first=0.15s  median= 9.16s  last=15.17s
reader pages, CDN budget @600rpm c4, 24 pages, 150ms  first=0.15s  median= 1.36s  last= 2.47s
covers, 6 srcs unlimited rpm c2, 60 covers, 300ms, cap=4   median=3.31s  last=6.02s
covers, same but global cap=16                              median=0.91s  last=1.51s
```

**2. قاعدة البيانات (`bench_db.py`):** SQLite بكل الـ migrations، عمل واحد، وN شابتر. الأزمنة بالـ ms (وسيط).

```
n=  300 first_refresh=   8.2  unchanged_refresh=   12.1  _units()=  1.8  lost(current)=    1.3 vs set-once=0.02
n= 1000 first_refresh=  16.4  unchanged_refresh=   32.5  _units()=  4.6  lost(current)=   10.5 vs set-once=0.04
n= 3000 first_refresh=  47.1  unchanged_refresh=  194.5  _units()= 11.7  lost(current)=  136.5 vs set-once=0.13
n= 6000 first_refresh= 174.6  unchanged_refresh= 1468.7  _units()= 29.1  lost(current)= 1211.7 vs set-once=0.37
record_signal (3000 rows): median 0.40 ms, max 0.72 ms; age-prune DELETE plan = SCAN source_health_signals
```

**3. `_validate_image` (صور ضوضاء، أي أسوأ حالة ضغط):**

```
300x450   JPEG 1.3ms  WEBP 6.4ms     |  800x1200  JPEG 8.7ms   WEBP 46.0ms
1100x1600 JPEG 14.8ms WEBP 97.2ms    |  800x1280  JPEG 9.2ms   WEBP 46.3ms
1600x2400 JPEG 39.3ms WEBP 188.9ms   |  720x10000 JPEG 83.8ms  WEBP 352.9ms
```

**4. `RecipeRuntime` على fixtures الأدابترات** (`bench_parse.py`، 538 حالة، وسيط 5 تكرارات). أعلى الحالات:

```
78.5 ms oneshelf.3asq catalog (171 KiB, 404 items) | 35.8 ms chitanka catalog | 18.9 ms comic-book-plus reader
```

**5. إقلاع وواجهة:**
- بناء وتحميل 9 حزم مضمّنة: 106 ms، واستيراد الوحدات الأساسية: 253 ms.
- `vite build`: `index-*.js` 675.85 kB (209.58 kB gzip)، و`pdf-*.js` 434.04 kB (129.34 kB gzip)، و`ReadRoute-*.js` 68.13 kB.

**6. إحصاء الأدابترات (114 أدابتر):**
- rpm: {6: 7، 10: 4، 12: 1، **20: 93**، 30: 8، 60: 1}.
- concurrency: {**1: 112**، 2: 2}.
- كتالوج متعدد الصفحات: webtoon (offset، 60)، وmangadex (offset، 40)، وtapas (page_number، 200)، وacomics (next_link، 200). الباقي صفحة واحدة.
- لا أدابتر يستخدم `fetch: browser`.

## ملحق (ب): أشياء غامضة تحتاج تأكيد

1. **المعدّل الحقيقي المسموح** لكل CDN (`*.pstatic.net`، و`*.tapas.io`، و`*.mangadex.network`). حد 20 rpm موروث من القالب، وما وجدت توثيقاً لسبب اختياره لكل مصدر.
2. **سبب `disableRange` في PDF** (أمني أو تبسيط). التعليق في `PdfView.tsx:136` يذكر إيقاف auto-fetch والطلبات المجزأة.
3. **طريقة الوصول البعيد** (remote/passkeys) وهل تمر عبر TLS أو HTTP/2، لأنها تغيّر أثر حد الاتصالات الستة.
4. **حجم مكتبة المستخدم الفعلي** (عدد الـ assets ومتوسط طول الكتالوج) لتقدير أثر `reconcile` والقوائم الطويلة.

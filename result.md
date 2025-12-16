# Lead Timezone & Call Prioritization API

## Kısa Özet
Bu API, telefon numaralarından **saat dilimi** tespit eder ve **en uygun arama zamanını** hesaplar. Çağrı merkezi operasyonları için tasarlanmıştır.

---

## Ne İşe Yarar?

Diyelim ki elinizde bir müşteri listesi var ve her müşterinin telefon numarası mevcut. Bu müşterileri aramak istiyorsunuz ama:
- Müşteri hangi ülkede ve saat diliminde?
- Şu an aranabilir mi? (07:00-18:59 arası mı?)
- Aranabilir değilse, ne zaman aranabilir?
- Hangi müşteriyi önce aramalıyım?

İşte bu API tam olarak bu soruları cevaplıyor.

---

## 5 Endpoint Var

| Endpoint | Amaç |
|----------|------|
| `POST /leads/raw` | Telefon numarasını temizle, ülke ve saat dilimini bul |
| `POST /leads/list` | Tüm lead'leri aranabilirlik durumuna göre listele ve sırala |
| `POST /leads/next-to-call` | Şu an aranması gereken en uygun lead'i seç |
| `POST /leads/call-window` | Türkiye 10:00-22:00 bazlı arama penceresini hesapla (tek numara) |
| `POST /leads/call-window/batch` | Türkiye 10:00-22:00 bazlı arama penceresini hesapla (toplu) |

---

## Endpoint 1: `/leads/raw`

### Ne Yapar?
Telefon numarasını alır, temizler ve şu bilgileri döner:
- Ülke kodu (ISO2)
- Saat dilimi (IANA formatında)
- Telefon numarası E164 formatında

### İstek Örneği
```json
[
  {
    "lead_id": "musteri-1",
    "phone_e164_or_digits": "+905321234567",
    "country_name": "Turkey"
  }
]
```

### Cevap Örneği
```json
[
  {
    "lead_id": "musteri-1",
    "phone_input": "+905321234567",
    "phone_digits": "905321234567",
    "phone_e164": "+905321234567",
    "country_name": "Turkey",
    "country_iso2": "TR",
    "timezone_iana": "Europe/Istanbul",
    "tz_ambiguous": false,
    "tz_source": "number"
  }
]
```

### Dönen Alanlar

| Alan | Açıklama |
|------|----------|
| `phone_input` | Gönderdiğiniz numara (olduğu gibi) |
| `phone_digits` | Sadece rakamlar |
| `phone_e164` | Uluslararası format (+ile) |
| `country_iso2` | Ülke kodu (2 harf): TR, US, GB... |
| `timezone_iana` | Saat dilimi: Europe/Istanbul, America/New_York... |
| `tz_ambiguous` | Birden fazla saat dilimi olabilir mi? |
| `tz_source` | Nereden bulundu: `number`, `country_fallback`, `empty` |

---

## Endpoint 2: `/leads/list`

### Ne Yapar?
Tüm lead'leri işler ve şu bilgileri hesaplar:
- Müşterinin yerel saati
- Şu an aranabilir mi?
- Aranabilir değilse ne zaman aranabilir?
- Öncelik puanı (hangi müşteriyi önce aramalı?)

Sonuçları **öncelik puanına göre sıralar** (en yüksek puan en üstte).

### İstek Örneği
```json
[
  {
    "lead_id": "musteri-1",
    "phone_e164_or_digits": "+905321234567",
    "country_name": "Turkey"
  },
  {
    "lead_id": "musteri-2",
    "phone_e164_or_digits": "+12125551234",
    "country_name": "United States"
  },
  {
    "lead_id": "musteri-3",
    "phone_e164_or_digits": "+81312345678",
    "country_name": "Japan"
  }
]
```

### Cevap Örneği
```json
[
  {
    "lead_id": "musteri-1",
    "phone_digits": "905321234567",
    "country_name": "Turkey",
    "timezone_iana": "Europe/Istanbul",
    "tz_ambiguous": false,
    "lead_local_time_now": "14:30:00",
    "can_call_now": true,
    "next_call_lead_local": "2025-12-16 14:30:00",
    "next_call_tr": "2025-12-16 14:30:00",
    "priority_score": 510
  },
  {
    "lead_id": "musteri-2",
    "phone_digits": "12125551234",
    "country_name": "United States",
    "timezone_iana": "America/New_York",
    "tz_ambiguous": true,
    "lead_local_time_now": "06:30:00",
    "can_call_now": false,
    "next_call_lead_local": "2025-12-16 07:00:00",
    "next_call_tr": "2025-12-16 15:00:00",
    "priority_score": 9970
  }
]
```

### Dönen Alanlar

| Alan | Açıklama |
|------|----------|
| `lead_local_time_now` | Müşterinin şu anki yerel saati |
| `can_call_now` | Şu an aranabilir mi? (07:00-18:59 arası) |
| `next_call_lead_local` | Müşterinin yerel saatinde ne zaman aranabilir |
| `next_call_tr` | Türkiye saatinde ne zaman aranabilir |
| `priority_score` | Öncelik puanı (yüksek = önce ara) |

### Öncelik Puanı Nasıl Hesaplanır?

**Şu an aranabilir lead'ler için:**
- Saat 13:00'e (öğlen) ne kadar yakınsa puan o kadar yüksek
- Mantık: Öğlen saatleri en verimli arama zamanı

**Şu an aranabilir olmayan lead'ler için:**
- Aranabilir olacağı zamana ne kadar az kaldıysa puan o kadar yüksek
- Mantık: Yakında aranabilir olacakları önce hazırla

---

## Endpoint 3: `/leads/next-to-call`

### Ne Yapar?
Tüm lead'ler arasından **şu an aranması gereken tek bir lead** seçer.

### Seçim Mantığı
1. Önce şu an aranabilir lead'lere bak (07:00-18:59 arası olanlar)
2. Aranabilir varsa → En yüksek öncelik puanlı olanı seç
3. Aranabilir yoksa → En yakın zamanda aranabilir olacak olanı seç

### İstek Örneği
```json
[
  {
    "lead_id": "musteri-1",
    "phone_e164_or_digits": "+905321234567"
  },
  {
    "lead_id": "musteri-2",
    "phone_e164_or_digits": "+12125551234"
  }
]
```

### Cevap Örneği (Aranabilir lead varsa)
```json
{
  "selected": {
    "lead_id": "musteri-1",
    "phone_digits": "905321234567",
    "country_name": "",
    "timezone_iana": "Europe/Istanbul",
    "tz_ambiguous": false,
    "lead_local_time_now": "14:30:00",
    "can_call_now": true,
    "next_call_lead_local": "2025-12-16 14:30:00",
    "next_call_tr": "2025-12-16 14:30:00",
    "priority_score": 510
  },
  "reason": "At least one lead is callable now (07:00–18:59 local). Selected the highest priority.",
  "total_leads": 2,
  "callable_now_count": 1
}
```

### Cevap Örneği (Aranabilir lead yoksa)
```json
{
  "selected": {
    "lead_id": "musteri-2",
    "phone_digits": "12125551234",
    "country_name": "",
    "timezone_iana": "America/New_York",
    "tz_ambiguous": true,
    "lead_local_time_now": "03:30:00",
    "can_call_now": false,
    "next_call_lead_local": "2025-12-17 07:00:00",
    "next_call_tr": "2025-12-17 15:00:00",
    "priority_score": 9500
  },
  "reason": "No lead is callable now. Selected the lead with the earliest next callable time (converted to TR).",
  "total_leads": 2,
  "callable_now_count": 0
}
```

### Dönen Alanlar

| Alan | Açıklama |
|------|----------|
| `selected` | Seçilen lead'in detayları (veya `null` eğer seçilemezse) |
| `reason` | Neden bu lead seçildi (açıklama) |
| `total_leads` | Toplam kaç lead işlendi |
| `callable_now_count` | Şu an kaç lead aranabilir durumda |

---

## Endpoint 4: `/leads/call-window`

### Ne Yapar?
Telefon numarası alır ve **Türkiye saati 10:00-22:00** aralığının müşterinin yerel saatindeki karşılığını hesaplar.

**Örnek:** 
- Türkiye 10:00-22:00 → New York 03:00-15:00
- Türkiye 10:00-22:00 → Tokyo 16:00-04:00 (ertesi gün)

### İstek Örneği
```json
{
  "phone_e164_or_digits": "+12125551234",
  "country_name": "United States"
}
```

### Cevap Örneği
```json
{
  "phone_input": "+12125551234",
  "phone_digits": "12125551234",
  "phone_e164": "+12125551234",
  "country_iso2": "US",
  "timezone_iana": "America/New_York",
  "tz_ambiguous": true,
  "local_start_time": "03:00",
  "local_end_time": "15:00",
  "lead_local_time_now": "08:30:45",
  "can_call_now": true,
  "description": "Türkiye saati 10:00-22:00 arası, müşterinin yerel saatinde 03:00-15:00 arasına denk gelir."
}
```

### Dönen Alanlar

| Alan | Açıklama |
|------|----------|
| `local_start_time` | Müşterinin yerel saatinde arama başlangıç saati (HH:MM) |
| `local_end_time` | Müşterinin yerel saatinde arama bitiş saati (HH:MM) |
| `lead_local_time_now` | Müşterinin şu anki yerel saati |
| `can_call_now` | Şu an Türkiye 10:00-22:00 aralığında mı? |
| `description` | Açıklama metni |

### Toplu İstek: `/leads/call-window/batch`

Birden fazla numara için aynı işlemi yapar:

```json
[
  {"phone_e164_or_digits": "+12125551234"},
  {"phone_e164_or_digits": "+905321234567"},
  {"phone_e164_or_digits": "+81312345678"}
]
```

---

## Arama Saatleri

API iki farklı arama penceresi kuralı kullanır:

### Eski Endpoint'ler için (leads/list, leads/next-to-call)

| Parametre | Değer |
|-----------|-------|
| Arama başlangıç saati | 07:00 (müşteri yerel saati) |
| Arama bitiş saati | 18:59 (müşteri yerel saati) |

### Yeni Endpoint için (leads/call-window)

| Parametre | Değer |
|-----------|-------|
| Türkiye başlangıç saati | 10:00 |
| Türkiye bitiş saati | 22:00 |
| Referans saat dilimi | Europe/Istanbul |

Bu değerler kodda `TR_CALL_START_HOUR`, `TR_CALL_END_HOUR` ve `TR_TZ` olarak tanımlıdır.

---

## Ülke Takma Adları

API bazı yaygın ülke isimlerini otomatik tanır:

| Girdi | Ülke Kodu |
|-------|-----------|
| "usa", "united states" | US |
| "uk", "united kingdom" | GB |
| "russia" | RU |
| "ivory coast", "cote d'ivoire" | CI |

---

## Kullanım Senaryoları

### Senaryo 1: Çağrı Merkezi Operasyonu
```
1. Müşteri listesini /leads/list'e gönder
2. can_call_now=true olanları filtrele
3. priority_score'a göre sırala
4. En yüksek puanlıdan başlayarak ara
```

### Senaryo 2: Tek Arama Seçimi
```
1. Müşteri listesini /leads/next-to-call'a gönder
2. Dönen "selected" lead'i ara
3. Aramayı tamamla
4. Listeyi güncelle ve tekrar gönder
```

### Senaryo 3: Veri Zenginleştirme
```
1. Ham müşteri verilerini /leads/raw'a gönder
2. Dönen ülke kodu ve saat dilimi bilgilerini CRM'e kaydet
3. Telefon numaralarını E164 formatında standartlaştır
```

### Senaryo 4: Türkiye Bazlı Arama Penceresi
```
1. Telefon numarasını /leads/call-window'a gönder
2. local_start_time ve local_end_time değerlerini al
3. Müşteriyi bu saatler arasında ara (Türkiye 10:00-22:00'ye denk gelir)
```

---

## API Dokümantasyonu

Uygulama çalışırken interaktif dokümantasyona erişebilirsiniz:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## Çalıştırma

```bash
# Bağımlılıkları yükle
pip3 install -r requirements.txt

# Uygulamayı başlat
python3 app.py
```

API `http://localhost:8000` adresinde çalışmaya başlayacaktır.

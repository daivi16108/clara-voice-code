# Roadmap: Clara Voice Code

## Overview

Превращаем прототип VoiceCoding в полноценное VS Code расширение. Фазы идут от базового рабочего цикла (tracer bullet) до публикации в Marketplace. Каждая фаза добавляет конкретный слой: сначала работает, потом удобно, потом готово к релизу.

## Phases

- [ ] **Phase 1: Tracer Bullet** — базовый цикл голос→Claude→голос в чистом проекте
- [ ] **Phase 2: Setup Wizard** — мастер установки, Groq API key, проверка Python
- [ ] **Phase 3: Personas & Languages** — Клара/Клод, RU/EN, авто-определение языка
- [ ] **Phase 4: All Input Modes** — wake word, диктовка, push-to-talk, off
- [ ] **Phase 5: Hands-Free Confirmation** — голосовые да/нет, голосовые отчёты
- [ ] **Phase 6: UX Polish** — статус-бар, звуки, настройки скорости/громкости
- [ ] **Phase 7: Marketplace Release** — публикация в VS Code Marketplace

## Phase Details

### Phase 1: Tracer Bullet
**Goal**: Базовый цикл работает в чистом VS Code проекте — говоришь, Claude слышит, отвечает голосом
**Depends on**: Nothing (first phase)
**Requirements**: [SC-1, SC-2, SC-3, SC-4, SC-5]
**Plans:** 3 plans
**Success Criteria** (what must be TRUE):
  1. VSIX устанавливается в чистый VS Code без ошибок
  2. MCP сервер регистрируется автоматически в .claude/settings.json
  3. Трей приложение запускается при активации расширения
  4. Голосовая команда через wake word попадает в Claude Code chat
  5. Claude отвечает голосом через voice_speak

Plans:
- [ ] 01-01-PLAN.md — Groq API key via SecretStorage + vitest setup + tray arg injection
- [ ] 01-02-PLAN.md — MCP auto-registration tests + user feedback messages
- [ ] 01-03-PLAN.md — Integration test + VSIX build + full cycle smoke test

### Phase 2: Setup Wizard
**Goal**: Новый пользователь запускает Clara с нуля за 2 минуты
**Depends on**: Phase 1
**Requirements**: US-1, US-2, US-3, US-4
**Success Criteria** (what must be TRUE):
  1. При первом запуске открывается Setup Wizard
  2. Wizard проверяет Python и предлагает установить если нет
  3. Wizard авто-устанавливает pip зависимости
  4. Wizard запрашивает Groq API key с инструкцией где взять
  5. После wizard расширение полностью работает
Plans:
- [ ] 02-01: Setup Wizard UI (webview) + Python detection
- [ ] 02-02: Auto pip install + API key flow + тест с нуля

### Phase 3: Personas & Languages
**Goal**: Пользователь выбирает персону (Клара/Клод) и язык (RU/EN)
**Depends on**: Phase 2
**Requirements**: US-7, US-8, US-9
**Success Criteria** (what must be TRUE):
  1. Переключение персоны меняет голос и wake word
  2. Авто-определение языка речи работает
  3. Интерфейс расширения на выбранном языке

Plans:
- [ ] 03-01: Persona settings + голосовые профили
- [ ] 03-02: Language auto-detection + i18n интерфейса

### Phase 4: All Input Modes
**Goal**: Все четыре режима ввода работают и переключаются из трея
**Depends on**: Phase 3
**Requirements**: US-10, US-11, US-12, US-13
**Success Criteria** (what must be TRUE):
  1. Wake word режим: активируется только после "Клара"/"Claude"
  2. Dictation режим: всё сказанное идёт в чат
  3. Push-to-talk: работает по горячей клавише
  4. Off режим: полное отключение
  5. Переключение режимов из трея

Plans:
- [ ] 04-01: Wake word detection + VAD improvements
- [ ] 04-02: Dictation mode + Push-to-talk + hotkey
- [ ] 04-03: Tray UI для переключения режимов

### Phase 5: Hands-Free Confirmation
**Goal**: Пользователь подтверждает действия Claude голосом, слышит голосовые отчёты
**Depends on**: Phase 4
**Requirements**: US-16, US-18
**Success Criteria** (what must be TRUE):
  1. "Да"/"Нет" голосом подтверждает/отклоняет действие Claude
  2. Claude даёт голосовой отчёт по завершению задачи
  3. voice_ask MCP tool работает

Plans:
- [ ] 05-01: voice_ask tool + голосовые да/нет
- [ ] 05-02: Голосовые отчёты о завершении задач

### Phase 6: UX Polish
**Goal**: Приятный опыт использования — статус видно, звуки слышно, скорость настраивается
**Depends on**: Phase 5
**Requirements**: US-14, US-15, US-19
**Success Criteria** (what must be TRUE):
  1. Статус-бар показывает текущее состояние (listening/processing/speaking/off)
  2. Звуковой сигнал при активации wake word (отключаемый)
  3. Настройки скорости и громкости голоса работают

Plans:
- [ ] 06-01: Status bar + звуковые уведомления
- [ ] 06-02: Settings UI (скорость, громкость, горячие клавиши)

### Phase 7: Marketplace Release
**Goal**: Расширение опубликовано в VS Code Marketplace
**Depends on**: Phase 6
**Requirements**: US-24
**Success Criteria** (what must be TRUE):
  1. Расширение проходит Marketplace review
  2. Установка одним кликом из Marketplace работает
  3. Privacy notice при первом запуске

Plans:
- [ ] 07-01: Marketplace prep (icons, описание, screenshots)
- [ ] 07-02: Privacy notice + финальное тестирование + публикация

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Tracer Bullet | 0/3 | Planning complete | - |
| 2. Setup Wizard | 0/2 | Not started | - |
| 3. Personas & Languages | 0/2 | Not started | - |
| 4. All Input Modes | 0/3 | Not started | - |
| 5. Hands-Free Confirmation | 0/2 | Not started | - |
| 6. UX Polish | 0/2 | Not started | - |
| 7. Marketplace Release | 0/2 | Not started | - |

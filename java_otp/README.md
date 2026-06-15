# OTP Backend Service

Простой сервис одноразовых OTP-кодов: регистрация, вход, генерация/проверка кодов и отправка по разным каналам.

## Запуск через Docker Compose
```bash
docker compose up --build
```

Сервисы:
- Swagger UI: http://localhost:8080/swagger-ui.html
- API: http://localhost:8080
- pgAdmin: http://localhost:5050 (admin@admin.com / admin)
- MailHog UI: http://localhost:8025
- PostgreSQL: localhost:5432 (otp/otp, db: otpdb)

## Основные API
### Auth
- `POST /auth/register` — регистрация (`ADMIN` только один).
- `POST /auth/login` — логин и выдача JWT.

### Admin (требуется роль ADMIN)
- `PUT /admin/config` — изменить длину OTP и TTL.
- `GET /admin/users` — список не-админов.
- `DELETE /admin/users/{id}` — удалить пользователя и его OTP.

### User (JWT)
- `POST /otp/generate` — генерация OTP (`channel`: `EMAIL|SMS|TELEGRAM|FILE`).
- `POST /otp/validate` — валидация OTP.

## Пример сценария
1. Зарегистрировать админа и пользователя.
2. Войти и получить JWT.
3. Отправить OTP в `FILE` или `EMAIL`.
4. Валидировать OTP по operationId + code.

### Значения по умолчанию при регистрации
- Если `email` не передан, автоматически ставится `demo@mailhog.local` (письмо можно увидеть в MailHog UI).
- Если `phone` не передан, сохраняется `none`.
- Если `telegramChatId` не передан, сохраняется `none`.
- Каналы SMS/TELEGRAM/FILE поддерживаются, но по умолчанию используется EMAIL через MailHog.

## Авторизация в Swagger
1. Вызовите `/auth/login` и скопируйте `token` из ответа.
2. Нажмите **Authorize** в Swagger UI.
3. Вставьте значение как `Bearer <ваш_токен>`.




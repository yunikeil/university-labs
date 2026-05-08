# Тестовый проект

Локальный DNS-фильтр с browser proxy и redirect proxy.

Домены для перехвата добавляются в `blocked_domains.txt`, по одному на строку:

```
example.com
```

Домены `.ru` открываются напрямую. Домены из `blocked_domains.txt` и остальные
домены отправляются на redirect proxy.

Перед возвратом proxy IP DNS отправляет подписанный UDP knock на redirect
proxy. Redirect proxy пускает только клиентов, которые недавно получили такой
DNS-ответ. В remote-режиме redirect proxy через iptables принимает входящие
TCP-подключения на любые порты и сам определяет исходный порт подключения.

## Local

Запуск полностью локально в Docker:

```
python scripts/compose.py --local
```

В браузере укажите ручной proxy:

```
HTTP proxy: 127.0.0.1
Port: 8080
Use this proxy for HTTPS: enabled
```

## Remote Redirect Proxy

Запуск с `redirect_proxy` на удалённом сервере:

```
python scripts/compose.py --remote root@90.156.254.49
```

При изменении локальных файлов deployer сам перезальёт `redirect_proxy.py` на
сервер и перезапустит systemd-сервис.

В `remote` и `local` режиме browser proxy сначала идёт к redirect proxy
обычным plain TCP-маршрутом. Если этот маршрут ловит timeout/reset/refused или
после TLS ClientHello не приходит первый ответ, browser proxy помечает
`host:port` как заблокированный провайдером и дальше использует кастомный
tunnel на порту `9443`. Домен, порт и первые байты
TLS/HTTP уходят между proxy зашифрованными кадрами, поэтому DPI на стороне
клиента не видит SNI целевого сайта.

```
$env:REDIRECT_PAIR_PORT="9443"
$env:REDIRECT_PAIR_SECRET="dev-secret-change-me"
python scripts/compose.py --remote root@90.156.254.49
```

```
$env:BROWSER_PROXY_TUNNEL_HOST=""
python scripts/compose.py --remote root@90.156.254.49
```

По умолчанию используется SSH-ключ из `~/.ssh/id_rsa`. Если ключ другой:

```
python scripts/compose.py --remote root@193.200.74.60 --ssh-dir C:\Users\you\.ssh --ssh-key /root/.ssh/my_key
```

## Ports

```
5353/udp  DNS
8080/tcp  browser proxy
80/tcp    redirect proxy HTTP
443/tcp   redirect proxy HTTPS
10080/tcp redirect proxy internal transparent listener
9443/tcp  custom proxy-pair tunnel
8081/tcp  block page
```

'use strict';
const infoTexts = {
  "uk": {
    "title": "Про Hemloc",
    "sections": [
      [
        "Призначення",
        [
          "Hemloc керує блокуванням IP-адрес і мереж. Через GoBGP він передає маршрути IPv4 та IPv6 на пограничні маршрутизатори провайдера, «отруюючи» таблицю маршрутизації. За відповідних політик маршрутизаторів трафік до зазначених адрес спрямовується в blackhole, і ці зовнішні ресурси стають недоступними з мережі провайдера.",
          "History розділяє зміни блокувань, користувачів і доступ, помилки та безпеку. Guest бачить зміни блокувань і п’ять останніх успішних входів у власній картці. Адміністратор бачить усі категорії. Налаштовуване зберігання та сповіщення через зовнішній скрипт типово вимкнені; доставка не гарантується і не підтверджує встановлення маршруту."
        ]
      ],
      [
        "ASN і IP networks list",
        [
          "Правило ASN блокує префікси, отримані з IRR для цієї автономної системи. IP networks list блокує лише введену IP-адресу або мережу; довідковий ASN не розширює блокування.",
          "Коментарі необов’язкові: у них можна зазначити підставу блокування або номер документа.",
          "Адреса може мати кілька причин блокування. Видалення одного правила не скасовує блокування за іншими правилами."
        ]
      ],
      [
        "Перевірка блокування",
        [
          "Після кожного додавання перевіряйте заблоковану адресу через MTR із мережі провайдера. Для ASN перевіряйте адреси з відповідних префіксів.",
          "Очікуваний результат: трасування доходить до ядра мережі та не проходить далі до заблокованої адреси. Якщо трасування виходить за межі мережі провайдера, перевірте маршрут, BGP-анонс і політики маршрутизатора.",
          "Відсутність відповідей MTR сама по собі не доводить блокування: маршрутизатори можуть не відповідати на діагностичні пакети. Порівнюйте трасування до та після зміни. Втрата відповідей проміжного вузла не означає блокування, якщо наступні вузли відповідають. За потреби перевіряйте маршрут на пограничному маршрутизаторі та доступність цільового сервісу."
        ]
      ],
      [
        "Master і slave",
        [
          "Якщо master недоступний, slave продовжує підтримувати блокування та BGP-анонси за останніми отриманими даними. Редагувати списки та користувачів у цьому режимі не можна.",
          "Очікуйте відновлення master. Якщо він повернувся з актуальною базою і ролі вузлів не змінювалися, робота продовжується у звичайному режимі. Master також можна відновити з резервної копії на іншому гіпервізорі.",
          "Якщо резервна копія не містить останніх змін, master неможливо відновити або потрібно негайно змінити блокування:",
          {
            "list": [
              "Переконайтеся, що старий master вимкнений або ізольований від мережі.",
              "Через консоль сервера в конфігураційному файлі Hemloc змініть роль slave на master.",
              "Перезапустіть сервіс Hemloc.",
              "Подальші зміни виконуйте на новому master."
            ]
          },
          "Для повернення старого master:",
          {
            "list": [
              "Запустіть його з відключеною мережею на гіпервізорі.",
              "Через консоль у конфігураційному файлі Hemloc змініть роль на slave, вкажіть адресу нового master та перевірте параметри авторизації й довіри реплікації.",
              "Перезапустіть сервіс Hemloc, потім відновіть мережевий доступ для реплікації, зберігаючи ізоляцію BGP.",
              "Дочекайтеся повної синхронізації та перевірте стан маршрутів. Лише після цього відновлюйте BGP-з’єднання."
            ]
          },
          {
            "note": "Важливо: сама зміна ролі на slave не зупиняє GoBGP та не відкликає старі маршрути. Якщо до завершення синхронізації відновити також BGP-з’єднання, вузол може тимчасово експортувати застарілі маршрути. Доступ для реплікації потрібно відновлювати окремо від BGP."
          },
          "Під час повної пересинхронізації стара база резервується, а репліковані дані замінюються актуальними даними нового master. Локальна конфігурація та protection зберігаються. Старі й нові гілки змін автоматично не об’єднуються.",
          "Новий slave можна розгорнути пізніше за інструкцією. Із чинним master потрібно узгодити protected ASN і префікси, накопичений protection cache, параметри IRR, атрибути маршрутів та налаштування авторизації й довіри реплікації. Новий вузол повинен мати власні node ID, локальні адреси та сертифікат із приватним ключем. Правила, користувачі й історія надходять через реплікацію.",
          "Після зміни ролей старий master не можна просто підключати до мережі: він не знає про нові зміни та може відновити застарілі анонси."
        ]
      ],
      [
        "Protection",
        [
          "Захищені ASN і префікси задаються під час налаштування серверів у конфігураційному файлі Hemloc на кожному вузлі. Конфігурація редагується через консоль; змінити protection через веб неможливо.",
          "Захищений ASN, сам захищений префікс і будь-які специфічніші мережі всередині нього заблокувати не можна. Менш специфічний агрегат, який охоплює захищену мережу, дозволений.",
          "Наприклад, для protected 192.0.2.0/24 заборонені: 192.0.2.0/24, 192.0.2.128/25 та 192.0.2.1/32. Префікс 192.0.0.0/16 дозволений. Логіка однакова для IPv4, IPv6 і приватних мереж.",
          "Префікси захищених ASN доповнюють локальний protection. Помилка джерела не скасовує останній збережений набір захисту.",
          {
            "protection": true
          }
        ]
      ],
      [
        "Можливі State маршруту на Dashboard",
        [
          "State показує стан маршруту в локальній таблиці маршрутизації GoBGP з урахуванням protection і результатів перевірки. Це не підтвердження експорту або прийняття маршруту роутером.",
          {
            "states": [
              [
                "Applied",
                "Свіжа перевірка підтвердила наявність локального маршруту Hemloc із потрібними атрибутами."
              ],
              [
                "Pending",
                "Маршрут очікується, але його локальне застосування ще не підтверджене; помилки застосування немає."
              ],
              [
                "Failed",
                "Потрібного локального маршруту немає; є помилка застосування або не налаштований next-hop відповідного сімейства."
              ],
              [
                "Excluded by protection",
                "Префікс виключений захистом із набору для анонсування. Раніше створений маршрут може очікувати відкликання."
              ],
              [
                "Unknown",
                "Немає достовірного спостереження поточного стану локальної RIB GoBGP."
              ],
              [
                "Stale",
                "Останнє спостереження локальної RIB GoBGP старше 45 секунд."
              ]
            ]
          }
        ]
      ]
    ],
    "protectionLabels": {
      "node": "Поточний вузол",
      "asns": "Захищені ASN",
      "prefixes": "Захищені префікси",
      "asn": "ASN",
      "prefix": "Префікс",
      "source": "Джерело",
      "configuration": "Конфігурація",
      "cache": "Збережений cache",
      "success": "Останнє успішне розкриття",
      "never": "Ще не розкритий",
      "loading": "Завантаження локального protection…",
      "error": "Локальний protection недоступний.",
      "filter": "Фільтр",
      "empty": "Немає результатів",
      "first": "Перша",
      "previous": "Попередня",
      "next": "Наступна",
      "last": "Остання",
      "page": "Сторінка",
      "of": "з",
      "showing": "Показано",
      "state": "State",
      "meaning": "Значення",
      "loaded": "Завантажена локальна конфігурація та збережений protection cache. Префікси з обох джерел залишаються захищеними."
    }
  },
  "en": {
    "title": "About Hemloc",
    "sections": [
      [
        "Purpose",
        [
          "Hemloc manages the blocking of IP addresses and networks. Through GoBGP it sends IPv4 and IPv6 routes to the provider’s border routers, “poisoning” the routing table. With the appropriate router policies, traffic to the specified addresses is directed into a blackhole, making these external resources unavailable from the provider’s network.",
          "History separates blocklist changes, users and access, and errors and security. Guests can view blocklist changes and their own five most recent successful sign-ins. Administrators can view all categories. Configurable retention and external-script notifications are disabled by default; notifications are best effort and do not confirm route installation."
        ]
      ],
      [
        "ASN and IP networks list",
        [
          "An ASN rule blocks the prefixes obtained from IRR for that autonomous system. IP networks list blocks only the IP address or network entered; reference ASN information does not expand the block.",
          "Comments are optional: they can record the reason for blocking or a document number.",
          "An address can have several reasons for being blocked. Deleting one rule does not remove blocking required by other rules."
        ]
      ],
      [
        "Checking a block",
        [
          "After every addition, check the blocked address using MTR from within the provider’s network. For an ASN, check addresses from the relevant prefixes.",
          "The expected result is that the trace reaches the network core and goes no further towards the blocked address. If the trace leaves the provider’s network, check the route, BGP announcement and router policies.",
          "Missing MTR replies alone do not prove blocking: routers may not respond to diagnostic packets. Compare traces before and after the change. A lack of replies from an intermediate hop does not mean blocking if later hops respond. If necessary, check the route on the border router and the availability of the target service."
        ]
      ],
      [
        "Master and slave",
        [
          "If the master is unavailable, the slave continues maintaining blocks and BGP announcements using the last data received. Lists and users cannot be edited in this mode.",
          "Wait for the master to recover. If it returns with an up-to-date database and node roles have not changed, normal operation resumes. The master can also be restored from a backup on another hypervisor.",
          "If the backup does not contain the latest changes, the master cannot be restored, or blocks must be changed immediately:",
          {
            "list": [
              "Make sure the old master is powered off or isolated from the network.",
              "Through the server console, change the slave role to master in the Hemloc configuration file.",
              "Restart the Hemloc service.",
              "Make further changes on the new master."
            ]
          },
          "To return the old master:",
          {
            "list": [
              "Start it with networking disconnected at the hypervisor.",
              "Through the console, change its role to slave in the Hemloc configuration file, specify the new master’s address, and check replication authentication and trust settings.",
              "Restart the Hemloc service, then restore network access for replication while keeping BGP isolated.",
              "Wait for full synchronization and check the routes. Restore BGP connectivity only after that."
            ]
          },
          {
            "note": "Important: changing the role to slave does not stop GoBGP or withdraw old routes. If BGP connectivity is restored before synchronization finishes, the node may temporarily export stale routes. Restore replication access separately from BGP."
          },
          "During full resynchronization, the old database is backed up and replicated data is replaced with current data from the new master. Local configuration and protection are preserved. Old and new branches of changes are not merged automatically.",
          "A new slave can be deployed later following the instructions. Coordinate protected ASNs and prefixes, the accumulated protection cache, IRR parameters, route attributes, and replication authentication and trust settings with the current master. The new node must have its own node ID, local addresses, and certificate with a private key. Rules, users and history arrive through replication.",
          "After a role change, do not simply reconnect the old master to the network: it does not know about new changes and may resume stale announcements."
        ]
      ],
      [
        "Protection",
        [
          "Protected ASNs and prefixes are set in each node’s Hemloc configuration file when the servers are configured. Edit the configuration through the console; protection cannot be changed through the web interface.",
          "A protected ASN, a protected prefix itself, and any more-specific networks inside it cannot be blocked. A less-specific aggregate that covers the protected network is allowed.",
          "For example, with protected 192.0.2.0/24, the following are forbidden: 192.0.2.0/24, 192.0.2.128/25 and 192.0.2.1/32. Prefix 192.0.0.0/16 is allowed. The same logic applies to IPv4, IPv6 and private networks.",
          "Prefixes of protected ASNs extend local protection. A source failure does not remove the last saved protection set.",
          {
            "protection": true
          }
        ]
      ],
      [
        "Possible route State values on Dashboard",
        [
          "State shows the route’s status in the local GoBGP routing table, taking protection and inspection results into account. It does not confirm export or acceptance by a router.",
          {
            "states": [
              [
                "Applied",
                "A fresh inspection confirmed a local Hemloc route with the required attributes."
              ],
              [
                "Pending",
                "The route is expected, but local application has not yet been confirmed; there is no application error."
              ],
              [
                "Failed",
                "The required local route is absent; there is an application error or no next-hop is configured for the address family."
              ],
              [
                "Excluded by protection",
                "Protection excluded the prefix from the announcement set. A previously created route may be awaiting withdrawal."
              ],
              [
                "Unknown",
                "There is no reliable observation of the current local GoBGP RIB state."
              ],
              [
                "Stale",
                "The last observation of the local GoBGP RIB is older than 45 seconds."
              ]
            ]
          }
        ]
      ]
    ],
    "protectionLabels": {
      "node": "Current node",
      "asns": "Protected ASNs",
      "prefixes": "Protected prefixes",
      "asn": "ASN",
      "prefix": "Prefix",
      "source": "Source",
      "configuration": "Configuration",
      "cache": "Retained cache",
      "success": "Last successful expansion",
      "never": "Not yet expanded",
      "loading": "Loading local protection…",
      "error": "Local protection is unavailable.",
      "filter": "Filter",
      "empty": "No results",
      "first": "First",
      "previous": "Previous",
      "next": "Next",
      "last": "Last",
      "page": "Page",
      "of": "of",
      "showing": "Showing",
      "state": "State",
      "meaning": "Meaning",
      "loaded": "Loaded local configuration and retained protection cache. Prefixes from either source remain protected."
    }
  },
  "ru": {
    "title": "О Hemloc",
    "sections": [
      [
        "Назначение",
        [
          "Hemloc управляет блокировкой IP-адресов и сетей. Через GoBGP он передаёт маршруты IPv4 и IPv6 на пограничные маршрутизаторы провайдера, «отравляя» таблицу маршрутизации. При соответствующих политиках маршрутизаторов трафик к указанным адресам направляется в blackhole, и эти внешние ресурсы становятся недоступны из сети провайдера.",
          "History разделяет изменения блокировок, пользователей и доступ, ошибки и безопасность. Guest видит изменения блокировок и пять последних успешных входов в своей карточке. Администратор видит все категории. Настраиваемое хранение и уведомления через внешний скрипт по умолчанию выключены; доставка не гарантируется и не подтверждает установку маршрута."
        ]
      ],
      [
        "ASN и IP networks list",
        [
          "Правило ASN блокирует префиксы, полученные из IRR для этой автономной системы. IP networks list блокирует только введённый IP-адрес или сеть; справочный ASN не расширяет блокировку.",
          "Комментарии необязательны: в них можно указать основание блокировки или номер документа.",
          "У адреса может быть несколько причин блокировки. Удаление одного правила не отменяет блокировку по другим правилам."
        ]
      ],
      [
        "Проверка блокировки",
        [
          "После каждого добавления проверяйте заблокированный адрес через MTR из сети провайдера. Для ASN проверяйте адреса из соответствующих префиксов.",
          "Ожидаемый результат: трассировка доходит до ядра сети и не проходит дальше к заблокированному адресу. Если трассировка выходит за пределы сети провайдера, проверьте маршрут, BGP-анонс и политики маршрутизатора.",
          "Отсутствие ответов MTR само по себе не доказывает блокировку: маршрутизаторы могут не отвечать на диагностические пакеты. Сравнивайте трассировки до и после изменения. Потеря ответов промежуточного узла не означает блокировку, если следующие узлы отвечают. При необходимости проверяйте маршрут на пограничном маршрутизаторе и доступность целевого сервиса."
        ]
      ],
      [
        "Master и slave",
        [
          "Если master недоступен, slave продолжает поддерживать блокировки и BGP-анонсы по последним полученным данным. Редактировать списки и пользователей в этом режиме нельзя.",
          "Ожидайте восстановления master. Если он вернулся с актуальной базой и роли узлов не менялись, работа продолжается в обычном режиме. Master также можно восстановить из резервной копии на другом гипервизоре.",
          "Если резервная копия не содержит последних изменений, master невозможно восстановить или необходимо немедленно изменить блокировки:",
          {
            "list": [
              "Убедитесь, что старый master выключен или изолирован от сети.",
              "Через консоль сервера в конфигурационном файле Hemloc измените роль slave на master.",
              "Перезапустите сервис Hemloc.",
              "Дальнейшие изменения выполняйте на новом master."
            ]
          },
          "Для возврата старого master:",
          {
            "list": [
              "Запустите его с отключённой сетью на гипервизоре.",
              "Через консоль в конфигурационном файле Hemloc измените роль на slave, укажите адрес нового master и проверьте параметры авторизации и доверия репликации.",
              "Перезапустите сервис Hemloc, затем восстановите сетевой доступ для репликации, сохраняя изоляцию BGP.",
              "Дождитесь полной синхронизации и проверьте состояние маршрутов. Только после этого восстанавливайте BGP-соединения."
            ]
          },
          {
            "note": "Важно: сама смена роли на slave не останавливает GoBGP и не отзывает старые маршруты. Если до завершения синхронизации восстановить также BGP-соединения, узел может временно экспортировать устаревшие маршруты. Доступ для репликации нужно восстанавливать отдельно от BGP."
          },
          "При полной пересинхронизации старая база резервируется, а реплицируемые данные заменяются актуальными данными нового master. Локальная конфигурация и protection сохраняются. Старые и новые ветки изменений автоматически не объединяются.",
          "Новый slave можно развернуть позже по инструкции. С действующим master необходимо согласовать protected ASN и префиксы, накопленный protection cache, параметры IRR, атрибуты маршрутов и настройки авторизации и доверия репликации. У нового узла должны быть собственные node ID, локальные адреса и сертификат с приватным ключом. Правила, пользователи и история поступают через репликацию.",
          "После смены ролей старый master нельзя просто подключать к сети: он не знает о новых изменениях и может восстановить устаревшие анонсы."
        ]
      ],
      [
        "Protection",
        [
          "Защищённые ASN и префиксы задаются при настройке серверов в конфигурационном файле Hemloc на каждом узле. Конфигурация редактируется через консоль; изменить protection через веб нельзя.",
          "Защищённый ASN, сам защищённый префикс и любые более специфичные сети внутри него заблокировать нельзя. Менее специфичный агрегат, который охватывает защищённую сеть, разрешён.",
          "Например, для protected 192.0.2.0/24 запрещены: 192.0.2.0/24, 192.0.2.128/25 и 192.0.2.1/32. Префикс 192.0.0.0/16 разрешён. Логика одинакова для IPv4, IPv6 и приватных сетей.",
          "Префиксы защищённых ASN дополняют локальный protection. Ошибка источника не отменяет последний сохранённый набор защиты.",
          {
            "protection": true
          }
        ]
      ],
      [
        "Возможные State маршрута на Dashboard",
        [
          "State показывает состояние маршрута в локальной таблице маршрутизации GoBGP с учётом protection и результатов проверки. Это не подтверждение экспорта или принятия маршрута роутером.",
          {
            "states": [
              [
                "Applied",
                "Свежая проверка подтвердила наличие локального маршрута Hemloc с нужными атрибутами."
              ],
              [
                "Pending",
                "Маршрут ожидается, но его локальное применение ещё не подтверждено; ошибки применения нет."
              ],
              [
                "Failed",
                "Нужного локального маршрута нет; есть ошибка применения или не настроен next-hop соответствующего семейства."
              ],
              [
                "Excluded by protection",
                "Префикс исключён защитой из набора для анонсирования. Ранее созданный маршрут может ожидать отзыва."
              ],
              [
                "Unknown",
                "Нет достоверного наблюдения текущего состояния локальной RIB GoBGP."
              ],
              [
                "Stale",
                "Последнее наблюдение локальной RIB GoBGP старше 45 секунд."
              ]
            ]
          }
        ]
      ]
    ],
    "protectionLabels": {
      "node": "Текущий узел",
      "asns": "Защищённые ASN",
      "prefixes": "Защищённые префиксы",
      "asn": "ASN",
      "prefix": "Префикс",
      "source": "Источник",
      "configuration": "Конфигурация",
      "cache": "Сохранённый cache",
      "success": "Последнее успешное раскрытие",
      "never": "Ещё не раскрыт",
      "loading": "Загрузка локального protection…",
      "error": "Локальный protection недоступен.",
      "filter": "Фильтр",
      "empty": "Нет результатов",
      "first": "Первая",
      "previous": "Предыдущая",
      "next": "Следующая",
      "last": "Последняя",
      "page": "Страница",
      "of": "из",
      "showing": "Показано",
      "state": "State",
      "meaning": "Значение",
      "loaded": "Загруженная локальная конфигурация и сохранённый protection cache. Префиксы из обоих источников остаются защищёнными."
    }
  }
};

const stateSummary='State describes desired eligibility and fresh local GoBGP observations. It does not confirm export or acceptance by a remote router. Open Info for all definitions.';
const routeStateDescriptions={
  'Applied':'Desired and observed within 45 seconds, with no newer observation failure: a locally originated Hemloc-owned path has the configured next-hop, local preference and communities.',
  'Pending':'Desired, with a fresh local observation, but no matching local path. No stored reconciliation error and a next-hop is configured. This can include disabled announcements; it does not mean installation succeeded.',
  'Failed':'Desired and freshly observed, with no matching local path, and either a stored reconciliation error or no next-hop configured for this family. A stored error can affect multiple pending prefixes.',
  'Excluded by protection':'The source prefix is absent from the desired set after local protected-prefix or protected-ASN checks. An old local path may still await withdrawal.',
  'Unknown':'Desired, but no timestamped local RIB observation is available, or a newer observation attempt failed. Application is not confirmed.',
  'Stale':'Desired, but the last timestamped local RIB observation is older than 45 seconds. Old local presence does not confirm current application.'
};

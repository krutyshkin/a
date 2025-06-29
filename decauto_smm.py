from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
if TYPE_CHECKING:
    from cardinal import Cardinal

from urllib.parse import quote
import re
import os
import json
import logging
import threading
import requests
import shutil
import time
import io
import sys
import subprocess

from datetime import datetime, timedelta

from FunPayAPI.updater.events import NewMessageEvent, NewOrderEvent
from FunPayAPI import enums

import uuid
import hashlib
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    import pymysql
except ImportError:
    import sys
    import subprocess
    print("Библиотека pymysql не установлена. Устанавливаем...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pymysql"])
    import pymysql
    print("Библиотека pymysql успешно установлена!")
    

NAME = "AutoSMM"
VERSION = "4.2"
DESCRIPTION = "Плагин для автоматической накрутки через 2+ сервис"
CREDITS = "@exfador"
UUID = "c800e7e9-05ce-43eb-addc-4f5841f79726"
SETTINGS_PAGE = False

MAC_ID = hex(uuid.getnode()).replace('0x', '')
HASH_MAC = hashlib.sha256(MAC_ID.encode()).hexdigest()[17:32]

IS_ACTIVATED = True

LOGGER_PREFIX = "[AUTO autosmm]"
logger = logging.getLogger("FPC.autosmm")

waiting_for_lots_upload = set()

UPDATE = """
Примечания к обновлению:

- Можно включить/выключить подтверждение ссылки
- Теперь правильно считается чистая прибыль
- Исправлены некоторые мелкие баги
"""

# def check_activation() -> bool:
#     global IS_ACTIVATED
#     try:
#         result = check_activation_sync()
#         IS_ACTIVATED = result
#         return result
#     except Exception as e:
#         logger.error(f"{LOGGER_PREFIX} Ошибка проверки активации: {e}")
#         return False

# def check_activation_sync() -> bool:
#     """Синхронная версия проверки активации"""
#     try:
#         if not hasattr(pymysql, 'connect'):
#             logger.error(f"{LOGGER_PREFIX} Ошибка: функция connect не найдена в модуле pymysql")
#             return False
            
#         connect_func = pymysql.connect
#         if connect_func is None:
#             logger.error(f"{LOGGER_PREFIX} Ошибка: функция connect в модуле pymysql равна None")
#             return False
            
#         conn = None
#         try:
#             conn = connect_func(
#                 host='185.188.182.159',
#                 user='requ',
#                 password='xz222000',
#                 db='plugins',
#                 charset='utf8mb4',
#                 connect_timeout=10
#             )
#         except Exception as conn_err:
#             logger.error(f"{LOGGER_PREFIX} Ошибка при создании соединения с БД: {conn_err}")
#             return False
            
#         if conn is None:
#             logger.error(f"{LOGGER_PREFIX} Соединение с БД вернуло None")
#             return False
            
#         try:
#             with conn.cursor() as cursor:
#                 cursor.execute("SELECT * FROM smm WHERE plugin_key = %s", (HASH_MAC,))
#                 result = cursor.fetchone()
                
#             conn.close()
            
#             if result:
#                 return True
#             return False
#         except Exception as query_err:
#             logger.error(f"{LOGGER_PREFIX} Ошибка при выполнении запроса к БД: {query_err}")
#             try:
#                 if conn:
#                     conn.close()
#             except:
#                 pass
#             return False
#     except Exception as e:
#         logger.error(f"{LOGGER_PREFIX} Общая ошибка при подключении к БД: {e}")
#         return False

# check_activation()

VALID_LINKS_PATH = os.path.join("storage", "cache", "valid_link.json")

def load_valid_links() -> List[str]:
    if os.path.exists(VALID_LINKS_PATH):
        with open(VALID_LINKS_PATH, 'r', encoding='utf-8') as f:
            links = json.load(f)
            if not links:
                default_links = [
                    "vk.com", "t.me", "instagram.com", "tiktok.com", "youtube.com",
                    "youtu.be", "twitch.tv", "vt.tiktok.com", "vm.tiktok.com",
                    "www.youtu.be", "www.youtube.com", "twitter.com"
                ]
                save_valid_links(default_links)
                return default_links
            return links
    else:
        default_links = [
            "vk.com", "t.me", "instagram.com", "tiktok.com", "youtube.com",
            "youtu.be", "twitch.tv", "vt.tiktok.com", "vm.tiktok.com",
            "www.youtu.be", "www.youtube.com", "twitter.com"
        ]
        save_valid_links(default_links)
        return default_links

def save_valid_links(links: List[str]):
    os.makedirs(os.path.dirname(VALID_LINKS_PATH), exist_ok=True)
    with open(VALID_LINKS_PATH, 'w', encoding='utf-8') as f:
        json.dump(links, f, ensure_ascii=False, indent=4)

def add_website(message: types.Message, new_site: str):
    valid_links = load_valid_links()
    if new_site not in valid_links:
        valid_links.append(new_site)
        save_valid_links(valid_links)
        bot.send_message(message.chat.id, f"✅ Сайт {new_site} успешно добавлен в список.")
    else:
        bot.send_message(message.chat.id, f"❌ Сайт {new_site} уже есть в списке.")

def remove_website(message: types.Message, site_to_remove: str):
    valid_links = load_valid_links()
    if site_to_remove in valid_links:
        valid_links.remove(site_to_remove)
        save_valid_links(valid_links)
        bot.send_message(message.chat.id, f"✅ Сайт {site_to_remove} успешно удалён из списка.")
    else:
        bot.send_message(message.chat.id, f"❌ Сайт {site_to_remove} не найден в списке.")

LOG_DIR = os.path.join("storage", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "auto_smm.log")

logger = logging.getLogger("FPC.autosmm")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_PATH, encoding='utf-8')
file_handler.setLevel(logging.ERROR)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

RUNNING = False
IS_STARTED = False
ORDER_CHECK_THREAD = None
AUTO_LOTS_SEND_THREAD = None

orders_info = {}
processed_users = {}
waiting_for_link: Dict[str, Dict] = {}

bot = None
config = {}
lot_mapping = {}
cardinal_instance = None

CONFIG_PATH = os.path.join("storage", "cache", "auto_lots.json")
ORDERS_PATH = os.path.join("storage", "cache", "auto_smm_orders.json")
ORDERS_DATA_PATH = os.path.join("storage", "cache", "orders_data.json")
os.makedirs(os.path.dirname(ORDERS_PATH), exist_ok=True)
os.makedirs(os.path.dirname(ORDERS_DATA_PATH), exist_ok=True)

def load_config() -> Dict:
    logger.info("Загрузка конфигурации (auto_lots.json)...")
    
    file_lock = threading.Lock()
    
    try:
        with file_lock:
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                        
                    if not file_content.strip():
                        logger.error(f"Файл конфигурации {CONFIG_PATH} пуст. Создаем новый файл конфигурации.")
                        cfg = create_default_config()
                        save_config(cfg)
                        return cfg
                        
                    try:
                        cfg = json.loads(file_content)
                    except json.JSONDecodeError as e:
                        logger.error(f"Ошибка при чтении JSON: {e}. Создаем новый файл конфигурации.")
                        cfg = create_default_config()
                        save_config(cfg)
                        return cfg
                    
                    if "services" not in cfg:
                        cfg["services"] = {
                            "1": {
                                "api_url": "https://service1.com/api/v2",
                                "api_key": "SERVICE_1_KEY"
                            },
                            "2": {
                                "api_url": "https://service2.com/api/v2",
                                "api_key": "SERVICE_2_KEY"
                            }
                        }
                    if "auto_refunds" not in cfg:
                        cfg["auto_refunds"] = True
                    if "confirm_link" not in cfg:
                        cfg["confirm_link"] = True
                    if "messages" not in cfg:
                        cfg["messages"] = {
                            "after_payment": "❤️ Благодарим за оплату!\n\nЧтобы начать накрутку, отправьте корректную ссылку на вашу страницу или пост в социальных сетях. Ссылка должна начинаться с \"https://\", например:\n\nПример: https://teletype.in/@exfador/wwTwed1ZBZE\n\nБез правильной ссылки накрутка не будет запущена. Убедитесь, что она ведет на активную страницу, доступную для общего просмотра.",
                            "after_confirmation": "🎉 Ваш заказ успешно оформлен!\n\n🔢 ID заказа в сервисе: {twiboost_id}\n🔗 Для отслеживания переходите по ссылке: {link}\n\n📋 Доступные команды:\n🔍 чек {twiboost_id} — Проверить статус заказа (выводит информацию о заказе)\n🔄 рефилл {twiboost_id} — Запросить рефилл (работает лишь с гарантией - восстанавливает отписанных подписчиков)\n\nЕсли у вас возникнут вопросы, не стесняйтесь обращаться!"
                        }
                    if "notification_chat_id" not in cfg:
                        cfg["notification_chat_id"] = None
                    if "send_auto_lots" not in cfg:
                        cfg["send_auto_lots"] = True
                    if "send_auto_lots_interval" not in cfg:
                        cfg["send_auto_lots_interval"] = 30
                    if "auto_start" not in cfg:
                        cfg["auto_start"] = True
                    if "lot_mapping" not in cfg:
                        cfg["lot_mapping"] = {}
                    if "new_order_notifications" not in cfg:
                        cfg["new_order_notifications"] = False
                    return cfg
                except Exception as e:
                    logger.error(f"Ошибка при чтении файла конфигурации: {e}. Создаем новый файл конфигурации.")
                    cfg = create_default_config()
                    save_config(cfg)
                    return cfg
            else:
                logger.info(f"Файл конфигурации {CONFIG_PATH} не найден. Создаем новый файл.")
                cfg = create_default_config()
                save_config(cfg)
                return cfg
    except Exception as e:
        logger.error(f"Общая ошибка при загрузке конфигурации: {e}. Возвращаем конфигурацию по умолчанию.")
        cfg = create_default_config()
        try:
            save_config(cfg)
        except:
            pass
        return cfg

def create_default_config() -> Dict:
    """Создает конфигурацию по умолчанию"""
    return {
        "services": {
            "1": {
                "api_url": "https://twiboost.com/api/v2",
                "api_key": "YOUR_API_KEY"
            }
        },
        "auto_refunds": True,
        "confirm_link": True,
        "messages": {
            "after_payment": "❤️ Благодарим за оплату!\n\nЧтобы начать накрутку, отправьте корректную ссылку на вашу страницу или пост в социальных сетях. Ссылка должна начинаться с \"https://\", например:\n\nПример: https://teletype.in/@exfador/wwTwed1ZBZE\n\nБез правильной ссылки накрутка не будет запущена. Убедитесь, что она ведет на активную страницу, доступную для общего просмотра.",
            "after_confirmation": "🎉 Ваш заказ успешно оформлен!\n\n🔢 ID заказа в сервисе: {twiboost_id}\n🔗 Для отслеживания переходите по ссылке: {link}\n\n📋 Доступные команды:\n🔍 чек {twiboost_id} — Проверить статус заказа (выводит информацию о заказе)\n🔄 рефилл {twiboost_id} — Запросить рефилл (работает лишь с гарантией - восстанавливает отписанных подписчиков)\n\nЕсли у вас возникнут вопросы, не стесняйтесь обращаться!"
        },
        "notification_chat_id": None,
        "send_auto_lots": True,
        "send_auto_lots_interval": 30,
        "auto_start": True,
        "lot_mapping": {},
        "new_order_notifications": False
    }

def save_config(cfg: Dict):
    logger.info("Сохранение конфигурации (auto_lots.json)...")
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    logger.info("Конфигурация сохранена.")

def reindex_lots(cfg: Dict):
    lot_map = cfg.get("lot_mapping", {})
    sorted_lots = sorted(
        lot_map.items(),
        key=lambda x: int(x[0].split('_')[1]) if x[0].startswith('lot_') and x[0].split('_')[1].isdigit() else 0
    )
    new_lot_map = {}
    for idx, (lot_key, lot_data) in enumerate(sorted_lots, start=1):
        new_key = f"lot_{idx}"
        new_lot_map[new_key] = lot_data
    cfg["lot_mapping"] = new_lot_map
    save_config(cfg)
    logger.info("Лоты были переиндексированы после удаления.")

def load_orders_data() -> List[Dict]:
    if not os.path.exists(ORDERS_DATA_PATH):
        return []
    try:
        with open(ORDERS_DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка при чтении orders_data.json: {e}")
        backup_path = f"{ORDERS_DATA_PATH}.bak.{int(time.time())}"
        try:
            shutil.copy2(ORDERS_DATA_PATH, backup_path)
            logger.info(f"Создана резервная копия поврежденного orders_data.json: {backup_path}")
        except Exception as ex:
            logger.error(f"Не удалось создать резервную копию orders_data.json: {ex}")
        
        try:
            with open(ORDERS_DATA_PATH, 'r', encoding='utf-8') as f:
                content = f.read()
            last_bracket_pos = content.rstrip().rfind(']')
            if last_bracket_pos > 0:
                valid_content = content[:last_bracket_pos+1]
                json.loads(valid_content)
                with open(ORDERS_DATA_PATH, 'w', encoding='utf-8') as f:
                    f.write(valid_content)
                logger.info("Файл orders_data.json успешно восстановлен")
                return json.loads(valid_content)
        except Exception as ex:
            logger.error(f"Не удалось восстановить orders_data.json: {ex}")
        
        return []

def save_orders_data(orders: List[Dict]):
    temp_path = f"{ORDERS_DATA_PATH}.tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(orders, f, indent=4, ensure_ascii=False)
        
        if os.path.exists(temp_path):
            if os.path.exists(ORDERS_DATA_PATH):
                os.remove(ORDERS_DATA_PATH)
            os.rename(temp_path, ORDERS_DATA_PATH)
        else:
            logger.error("Не удалось создать временный файл для безопасного сохранения orders_data.json")
    except Exception as e:
        logger.error(f"Ошибка при сохранении orders_data.json: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def save_order_data(
    chat_id: int,
    order_id: str,
    twiboost_id: int,
    status: str,
    chistota: float,
    customer_url: str,
    quantity: int,
    service_number: int,
    is_refunded: bool = False
):
    data_ = {
        "chat_id": chat_id,
        "order_id": order_id,
        "id_zakaz": twiboost_id,
        "status": status,
        "chistota": chistota,
        "customer_url": customer_url,
        "quantity": quantity,
        "service_number": service_number,
        "is_refunded": is_refunded,
        "spent": 0.0,
        "summa": chistota,
        "currency": "RUB"
    }
    
    orders = load_orders_data()
    
    orders.append(data_)
    
    save_orders_data(orders)
    
    logger.info(f"Данные заказа #{order_id} (twiboost ID: {twiboost_id}) сохранены.")

def save_order_info(order_id: int, order_summa: float, service_name: str, order_chistota: float):
    file_lock = threading.Lock()
    
    data_ = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "order_id": order_id,
        "summa": order_summa,
        "service_name": service_name,
        "chistota": order_chistota,
        "completed_notification_sent": False
    }
    
    try:
        with file_lock:
            if not os.path.exists(ORDERS_PATH):
                os.makedirs(os.path.dirname(ORDERS_PATH), exist_ok=True)
                with open(ORDERS_PATH, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4, ensure_ascii=False)
            
            try:
                with open(ORDERS_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content.strip():
                        orders = []
                    else:
                        orders = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка при чтении {ORDERS_PATH}: {e}. Создаем новый файл.")
                orders = []
            
            orders.append(data_)
            
            temp_path = f"{ORDERS_PATH}.tmp"
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(orders, f, indent=4, ensure_ascii=False)
                
                if os.path.exists(temp_path):
                    if os.path.exists(ORDERS_PATH):
                        os.remove(ORDERS_PATH)
                    os.rename(temp_path, ORDERS_PATH)
                    logger.info(f"Данные заказа #{order_id} успешно сохранены")
            except Exception as e:
                logger.error(f"Ошибка при сохранении данных заказа #{order_id}: {e}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
    except Exception as e:
        logger.error(f"Общая ошибка при сохранении информации о заказе #{order_id}: {e}")

def update_order_status(order_id_funpay: str, new_status: str):
    orders = load_orders_data()
    updated = False

    for order in orders:
        if str(order["order_id"]) == str(order_id_funpay):
            order["status"] = new_status
            updated = True
            logger.info(f"Статус заказа #{order_id_funpay} обновлён на '{new_status}'.")
            break

    if updated:
        save_orders_data(orders)
    else:
        logger.warning(f"Заказ #{order_id_funpay} не найден в orders_data.json.")

def update_order_refunded_status(order_id_funpay: str):
    orders = load_orders_data()
    updated = False
    for order in orders:
        if str(order["order_id"]) == str(order_id_funpay):
            if not order.get("is_refunded", False):
                order["is_refunded"] = True
                updated = True
                logger.info(f"Статус заказа #{order_id_funpay} обновлён на 'is_refunded': True.")
            break

    if updated:
        save_orders_data(orders)
    else:
        logger.warning(f"Заказ #{order_id_funpay} не найден или уже отмечен как 'is_refunded'.")

def refund_order(c: Cardinal, order_id_funpay: str, buyer_chat_id: int, reason: str, detailed_reason: str = None):
    """
    Обработка возврата средств с уведомлением клиента и получателя уведомлений.
    """
    cfg = load_config()
    auto_refunds = cfg.get("auto_refunds", True)
    notification_chat_id = cfg.get("notification_chat_id")

    if detailed_reason is None:
        detailed_reason = reason

    orders = load_orders_data()
    order_data = next((o for o in orders if str(o["order_id"]) == str(order_id_funpay)), None)
    
    if order_data and order_data.get("is_refunded", False):
        logger.info(f"Заказ #{order_id_funpay} уже был возвращен. Пропуск.")
        return

    order_url = f"https://funpay.com/orders/{order_id_funpay}/"

    if auto_refunds:
        try:
            c.account.refund(order_id_funpay)
            c.send_message(buyer_chat_id, f"❌ Ваши средства возвращены по причине: {reason}")
            if notification_chat_id:
                detailed_message = f"""
⚠️ Автоматический возврат средств для заказа #{order_id_funpay}.
🔢 Номер заказа: {order_id_funpay}
📝 Причина: {detailed_reason}
🔗 Ссылка на заказ: {order_url}
                """.strip()
                bot.send_message(notification_chat_id, detailed_message)
            logger.info(f"Заказ #{order_id_funpay} был отменён (refund) для покупателя {buyer_chat_id}. Причина: {reason}")

            waiting_for_link.pop(str(order_id_funpay), None)
        except Exception as ex:
            logger.error(f"Не удалось вернуть средства для заказа #{order_id_funpay}: {ex}")
            if notification_chat_id:
                detailed_message = f"""
⚠️ Ошибка при автоматическом возврате средств для заказа #{order_id_funpay}.
🔢 Номер заказа: {order_id_funpay}
📝 Причина: {detailed_reason}
❗ Ошибка: {ex}
🔗 Ссылка на заказ: {order_url}
                """.strip()
                bot.send_message(notification_chat_id, detailed_message)
    else:
        if notification_chat_id:
            detailed_message = f"""
⚠️ Требуется ручной возврат средств для заказа #{order_id_funpay}.
🔢 Номер заказа: {order_id_funpay}
📝 Причина: {detailed_reason}
🔗 Перейдите по ссылке, чтобы отменить заказ: {order_url}
            """.strip()
            bot.send_message(notification_chat_id, detailed_message)
        else:
            logger.warning("Notification chat_id не задан для уведомления о возврате.")


def update_order_charge_and_net(order_id_funpay: str, spent: float, currency: str = "USD", net_profit: float = None):
    orders_data = load_orders_data()
    found_od = False
    for order in orders_data:
        if str(order["order_id"]) == str(order_id_funpay):
            order["spent"] = spent
            order["currency"] = currency
            if net_profit is not None:
                order["chistota"] = net_profit
            else:
                net = order["summa"] - spent
                order["chistota"] = round(net, 2)
            found_od = True
            break

    if found_od:
        save_orders_data(orders_data)

    if os.path.exists(ORDERS_PATH):
        with open(ORDERS_PATH, 'r', encoding='utf-8') as f:
            orders_list = json.load(f)
        updated_a = False
        for o in orders_list:
            if str(o["order_id"]) == str(order_id_funpay):
                o["spent"] = spent
                o["currency"] = currency
                if net_profit is not None:
                    o["chistota"] = net_profit
                else:
                    net = o["summa"] - spent
                    o["chistota"] = round(net, 2)
                updated_a = True
                break

        if updated_a:
            with open(ORDERS_PATH, 'w', encoding='utf-8') as f:
                json.dump(orders_list, f, indent=4, ensure_ascii=False)

def check_order_status(
    c: Cardinal,
    twiboost_order_id: int,
    buyer_chat_id: int,
    link: str,
    order_id_funpay: str,
    attempt: int = 1
):
    """
    Потоковая проверка статуса заказа на соответствующем SMM-сервисе.
    """
    file_lock = threading.Lock()
    
    try:
        with file_lock:
            if os.path.exists(ORDERS_PATH):
                try:
                    with open(ORDERS_PATH, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                        if not file_content.strip():
                            orders_info = []
                        else:
                            orders_info = json.loads(file_content)
                except (json.JSONDecodeError, Exception) as e:
                    logger.error(f"Ошибка при чтении файла {ORDERS_PATH}: {e}")
                    orders_info = []
            else:
                orders_info = []
    except Exception as e:
        logger.error(f"Ошибка при доступе к файлу {ORDERS_PATH}: {e}")
        orders_info = []
    
    order_info = next((o for o in orders_info if str(o["order_id"]) == str(order_id_funpay)), None)
    if order_info and order_info.get("completed_notification_sent", False):
        logger.info(f"{LOGGER_PREFIX} Уведомление о завершении для заказа #{order_id_funpay} уже было отправлено. Пропускаем проверку.")
        return
    
    try:
        orders = load_orders_data()
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных о заказах: {e}")
        orders = []
    
    order_data = next((o for o in orders if str(o["order_id"]) == str(order_id_funpay)), None)
    if not order_data:
        logger.warning(f"Заказ {order_id_funpay} не найден при check_order_status.")
        order_data = {"service_number": 1}

    service_number = order_data["service_number"]
    
    try:
        cfg = load_config()
        service_cfg = cfg["services"].get(str(service_number))
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return
    
    if not service_cfg:
        logger.warning(f"Не найден config.services[{service_number}] — прерываем проверку.")
        return

    api_url = service_cfg["api_url"]
    api_key = service_cfg["api_key"]

    url_ = f"{api_url}?action=status&order={twiboost_order_id}&key={api_key}"
    logger.info(f"{LOGGER_PREFIX} Проверка статуса заказа #{twiboost_order_id}, попытка {attempt}...")

    completed_statuses = ["completed", "done", "success", "partial"]
    failed_statuses = ["failed", "error", "canceled"]

    try:
        response = requests.get(url_, timeout=10)
        logger.debug(f"Запрос к {url_} вернул статус {response.status_code}")
        if response.status_code == 200:
            data_ = response.json()
            status_ = data_.get("status", "Unknown")
            remains_ = data_.get("remains", "Unknown")
            charge_ = data_.get("charge", "0")
            currency_ = data_.get("currency", "USD")

            logger.info(f"Ответ сервиса #{twiboost_order_id}: {data_}")
            try:
                remains_ = int(remains_)
            except ValueError:
                remains_ = None
            try:
                spent_ = float(charge_)
            except ValueError:
                spent_ = 0.0

            status_lower = status_.lower()

            if status_lower in completed_statuses or (remains_ is not None and remains_ == 0):
                if order_info:
                    try:
                        with file_lock:
                            order_info["completed_notification_sent"] = True
                            with open(ORDERS_PATH, 'w', encoding='utf-8') as f:
                                json.dump(orders_info, f, indent=4, ensure_ascii=False)
                            logger.info(f"Успешно обновлен статус уведомления для заказа #{order_id_funpay}")
                    except Exception as e:
                        logger.error(f"Ошибка при сохранении статуса уведомления для заказа #{order_id_funpay}: {e}")

                order_link = f"https://funpay.com/orders/{order_id_funpay}/"
                message = (
                    f"🎉 Ваш заказ успешно завершён!\n"
                    f"🔢 Номер заказа: {twiboost_order_id}\n"
                    f"🔗 Подтвердите заказ: {order_link}"
                )
                c.send_message(buyer_chat_id, message)
                logger.info(f"Уведомление о завершении отправлено покупателю {buyer_chat_id} (заказ #{twiboost_order_id}).")

                return

            elif status_lower in failed_statuses:
                refund_order(
                    c,
                    order_id_funpay,
                    buyer_chat_id,
                    reason="Заказ не выполнен.",
                    detailed_reason=f"Заказ в сервисе имеет статус '{status_}'."
                )
                return

            else:
                logger.info(f"Заказ #{twiboost_order_id} в статусе '{status_}' (осталось: {remains_}).")
                delay = 300

        elif response.status_code == 429:
            logger.warning(f"Получен статус 429 (Too Many Requests) для заказа #{twiboost_order_id}.")
            delay = 3600


        else:
            logger.error(f"Ошибка при проверке заказа #{twiboost_order_id}: {response.status_code}, {response.text}")
            delay = 300

    except requests.exceptions.RequestException as req_ex:
        logger.error(f"RequestException при проверке #{twiboost_order_id}: {req_ex}")
        delay = min(300 * (2 ** (attempt - 1)), 3600)
    except Exception as ex:
        logger.error(f"Неизвестная ошибка при проверке заказа #{twiboost_order_id}: {ex}")
        delay = 300

    logger.info(f"Повторная проверка заказа #{twiboost_order_id} через {delay} сек.")
    threading.Timer(
        delay,
        check_order_status,
        args=(c, twiboost_order_id, buyer_chat_id, link, order_id_funpay, attempt + 1)
    ).start()

def start_order_checking(c: Cardinal):
    if RUNNING and IS_ACTIVATED:  
        try:
            all_data = load_orders_data()
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных о заказах в start_order_checking: {e}")
            all_data = []
        
        orders_info_data = []
        file_lock = threading.Lock()
        
        try:
            with file_lock:
                if os.path.exists(ORDERS_PATH):
                    try:
                        with open(ORDERS_PATH, 'r', encoding='utf-8') as f:
                            file_content = f.read()
                            if not file_content.strip():
                                orders_info_data = []
                            else:
                                orders_info_data = json.loads(file_content)
                    except (json.JSONDecodeError, Exception) as e:
                        logger.error(f"Ошибка при чтении файла {ORDERS_PATH} в start_order_checking: {e}")
                        orders_info_data = []
        except Exception as e:
            logger.error(f"Ошибка при доступе к файлу {ORDERS_PATH} в start_order_checking: {e}")
            orders_info_data = []
        
        for od_ in all_data:
            try:
                if od_["status"].lower() != "completed" and not od_.get("is_refunded", False):
                    order_info = next((o for o in orders_info_data if str(o["order_id"]) == str(od_["order_id"])), None)
                    if order_info and order_info.get("completed_notification_sent", False):
                        logger.info(f"{LOGGER_PREFIX} Пропуск проверки заказа #{od_['order_id']}, уведомление уже отправлено")
                        continue
                    
                    threading.Thread(
                        target=check_order_status,
                        args=(c, od_["id_zakaz"], od_["chat_id"], od_["customer_url"], od_["order_id"])
                    ).start()
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка при обработке заказа в start_order_checking: {e}")
                continue

def get_tg_id_by_description(description: str, order_amount: int) -> Tuple[int, int, int] | None:
    for lot_key, lot_data in lot_mapping.items():
        lot_name = lot_data["name"]
        if re.search(re.escape(lot_name), description, re.IGNORECASE):
            service_id = lot_data["service_id"]
            base_q = lot_data["quantity"]
            real_q = base_q * order_amount
            srv_num = lot_data.get("service_number", 1)
            return service_id, real_q, srv_num
    return None

def is_valid_link(link: str) -> Tuple[bool, str]:
    valid_links = load_valid_links()
    if not link.startswith(("http://", "https://")):
        return False, "❌ Ссылка должна начинаться с http:// или https://."
    for pf in valid_links:
        if pf in link:
            return True, f"✅ Ссылка корректна ({pf})."
    return False, "❌ Недопустимая ссылка."

def auto_smm_handler(c: Cardinal, e, *args):
    global RUNNING, orders_info, waiting_for_link

    if not IS_ACTIVATED:
        return

    if not RUNNING:
        return

    my_id = c.account.id
    bot_ = c.telegram.bot

    if isinstance(e, NewMessageEvent):
        if e.message.author_id == my_id:
            return

        msg_text = e.message.text.strip()
        msg_author_id = e.message.author_id
        msg_chat_id = e.message.chat_id

        logger.info(f"Новое сообщение от {e.message.author}: {msg_text}")

        m_check = re.match(r'^чек\s+(\d+)$', msg_text.lower())
        if m_check:
            order_num = m_check.group(1)
            od_ = load_orders_data()
            found = next((o for o in od_ if str(o["id_zakaz"]) == order_num), None)
            if not found:
                c.send_message(msg_chat_id, "❌ Заказ не найден в базе.")
                return
            cfg = load_config()
            service_cfg = cfg["services"].get(str(found["service_number"]))
            if not service_cfg:
                c.send_message(msg_chat_id, f"❌ Не найден конфиг для service_number={found['service_number']}")
                return
            api_url = service_cfg["api_url"]
            api_key = service_cfg["api_key"]
            url_ = f"{api_url}?action=status&order={order_num}&key={api_key}"
            try:
                rr = requests.get(url_)
                rr.raise_for_status()
                rdata = rr.json()
                st_ = rdata.get("status", "неизв.")
                rm_ = rdata.get("remains", "неизв.")
                ch_ = rdata.get("charge", "неизв.")
                cur_ = rdata.get("currency", "неизв.")
                c.send_message(msg_chat_id, f"Статус: {st_}")
            except Exception as ex:
                c.send_message(msg_chat_id, f"Ошибка при проверке")
            return

        m_refill = re.match(r'^рефилл\s+(\d+)$', msg_text.lower())
        if m_refill:
            order_num = m_refill.group(1)
            c.send_message(msg_chat_id, "Запрашиваю рефилл...")
            od_ = load_orders_data()
            found = next((o for o in od_ if str(o["id_zakaz"]) == order_num), None)
            if not found:
                c.send_message(msg_chat_id, "❌ Заказ не найден в базе.")
                return
            cfg = load_config()
            service_cfg = cfg["services"].get(str(found["service_number"]))
            if not service_cfg:
                c.send_message(msg_chat_id, f"❌ Не найден конфиг для service_number={found['service_number']}")
                return
            api_url = service_cfg["api_url"]
            api_key = service_cfg["api_key"]
            url_ = f"{api_url}?action=refill&order={order_num}&key={api_key}"
            try:
                rr = requests.get(url_)
                rr.raise_for_status()
                rdata = rr.json()
                st_ = rdata.get("status", 0)
                if str(st_) in ("1", "true"):
                    c.send_message(msg_chat_id, "✅ Рефилл успешно запущен.")
                else:
                    c.send_message(msg_chat_id, f"❌ Рефилл отклонён (status={st_}).")
            except Exception as ex:
                c.send_message(msg_chat_id, f"Ошибка при запросе рефилла")
            return

        for order_id, data in waiting_for_link.items():
            if data["buyer_id"] == msg_author_id:
                if data["step"] == "await_link":
                    link_m = re.search(r'(https?://\S+)', msg_text)
                    if not link_m:
                        c.send_message(msg_chat_id, "❌ Неверная ссылка, повторите...")
                        return
                    link_ = link_m.group(0)
                    ok, reason = is_valid_link(link_)
                    if not ok:
                        c.send_message(msg_chat_id, reason)
                        return
                    data["link"] = link_
                    
                    cfg = load_config()
                    confirm_link = cfg.get("confirm_link", True)
                    
                    if confirm_link:
                        data["step"] = "await_confirm"
                        c.send_message(msg_chat_id, f"✅ Ссылка принята: {link_}\nПодтвердите: + / -")
                        return
                    else:
                        process_link_without_confirmation(c, data)
                    return

                elif data["step"] == "await_confirm":
                    if msg_text.lower() == "+":
                        process_link_without_confirmation(c, data)
                        return
                    elif msg_text.lower() == "-":
                        data["step"] = "await_link"
                        c.send_message(msg_chat_id, "❌ Подтверждение отклонено. Введите другую ссылку.")
                        return
                    else:
                        c.send_message(msg_chat_id, "❌ Используйте + или -. Повторите.")
                        return

    elif isinstance(e, NewOrderEvent):
        order_ = e.order
        orderID = order_.id
        orderDesc = order_.description
        orderAmount = order_.amount
        orderPrice = order_.price

        logger.info(f"Новый заказ #{orderID}: {orderDesc}, x{orderAmount}")

        cfg = load_config()
        found_lot = get_tg_id_by_description(orderDesc, orderAmount)
        if found_lot is None:
            logger.info("Лот не найден по описанию. Пропуск обработки.")
            return

        service_id, real_amount, srv_number = found_lot

        od_full = c.account.get_order(orderID)
        buyer_chat_id = od_full.chat_id
        buyer_id = od_full.buyer_id
        buyer_username = od_full.buyer_username
        orders_info[orderID] = {
            "buyer_id": buyer_id,
            "chat_id": buyer_chat_id,
            "summa": orderPrice
        }

        save_order_info(orderID, orderPrice, orderDesc, orderPrice)

        try:
            msg_payment = cfg["messages"]["after_payment"].format(
                buyer_username=buyer_username,
                orderDesc=orderDesc,
                orderPrice=orderPrice,
                orderAmount=orderAmount
            )
        except KeyError as e:
            logger.error(f"Ошибка в шаблоне сообщения: отсутствует переменная {e}")
            msg_payment = "❤️ Спасибо за оплату! Укажите ссылку для запуска заказа."
        
        c.send_message(buyer_chat_id, msg_payment)

        waiting_for_link[str(orderID)] = {
            "buyer_id": buyer_id,
            "chat_id": buyer_chat_id,
            "service_id": service_id,
            "real_amount": real_amount,
            "order_id_funpay": orderID,
            "price": orderPrice,
            "service_number": srv_number,
            "step": "await_link"
        }

def start_smm(message: types.Message):
    global RUNNING, IS_STARTED, ORDER_CHECK_THREAD, AUTO_LOTS_SEND_THREAD, cardinal_instance

    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return

    if RUNNING:
        bot.send_message(message.chat.id, "✅ Плагин уже запущен.")
        return

    RUNNING = True
    IS_STARTED = True
    
    c_ = cardinal_instance
    
    if not ORDER_CHECK_THREAD or not ORDER_CHECK_THREAD.is_alive():
        ORDER_CHECK_THREAD = threading.Thread(target=start_order_checking, args=(c_,))
        ORDER_CHECK_THREAD.daemon = True
        ORDER_CHECK_THREAD.start()
    
    if not AUTO_LOTS_SEND_THREAD or not AUTO_LOTS_SEND_THREAD.is_alive():
        AUTO_LOTS_SEND_THREAD = threading.Thread(target=start_auto_lots_sender, args=(c_,))
        AUTO_LOTS_SEND_THREAD.daemon = True
        AUTO_LOTS_SEND_THREAD.start()
    
    bot.send_message(message.chat.id, "✅ Плагин успешно запущен.")

def stop_smm(message: types.Message):
    global RUNNING
    
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return

    if not RUNNING:
        bot.send_message(message.chat.id, "❌ Плагин не запущен.")
        return

    RUNNING = False
    bot.send_message(message.chat.id, "✅ Плагин остановлен.")

def auto_smm_delete(message: types.Message):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    if os.path.exists(ORDERS_PATH):
        os.remove(ORDERS_PATH)
    if os.path.exists(ORDERS_DATA_PATH):
        os.remove(ORDERS_DATA_PATH)
    bot.send_message(message.chat.id, "✅ Файлы заказов успешно удалены.")

def auto_smm_settings(message: types.Message):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return

    cfg = load_config()
    lmap = cfg.get("lot_mapping", {})
    auto_refunds = cfg.get("auto_refunds", True)
    confirm_link = cfg.get("confirm_link", True)
    notif_chat_id = cfg.get("notification_chat_id", "Не задан")
    send_auto_lots = cfg.get("send_auto_lots", True)
    send_auto_lots_interval = cfg.get("send_auto_lots_interval", 30)
    auto_start = cfg.get("auto_start", False)

    status_text = "✅ АКТИВИРОВАН" if IS_ACTIVATED else f"❌ НЕ АКТИВИРОВАН (Ключ: {HASH_MAC})"

    txt_ = f"""
🚀 <b>AUTOSMM ПАНЕЛЬ УПРАВЛЕНИЯ v{VERSION}</b> 🚀
━━━━━━━━━━━━━━━━━━━━━━━━
👨‍💻 <b>Разработчик:</b> {CREDITS}

📊 <b>СТАТУС:</b> {status_text}

💡 <b>ОСНОВНЫЕ ПАРАМЕТРЫ:</b>
 • Лотов в базе: <code>{len(lmap)}</code>
 • Автовозвраты: {'✅' if auto_refunds else '❌'}
 • Подтверждение ссылки: {'✅' if confirm_link else '❌'}
 • Отправка auto_lots.json: {'✅' if send_auto_lots else '❌'}
 • Интервал отправки: <code>{send_auto_lots_interval} мин</code>
 • Автозапуск: {'✅' if auto_start else '❌'}

📞 <b>УВЕДОМЛЕНИЯ:</b> <code>{notif_chat_id}</code>

📝 <b>О ПЛАГИНЕ:</b> <i>{DESCRIPTION}</i>
━━━━━━━━━━━━━━━━━━━━━━━━
    """.strip()

    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.add(
        InlineKeyboardButton("🛍️ Каталог лотов", callback_data="lot_settings"),
        InlineKeyboardButton("➕ Создать новый лот", callback_data="add_new_lot")
    )
    
    kb.add(
        InlineKeyboardButton("🔌 Интеграция API", callback_data="api_settings"),
    )
    
    kb.add(
        InlineKeyboardButton("🌐 Доверенные сайты", callback_data="manage_websites"),
        InlineKeyboardButton("💬 Шаблоны сообщений", callback_data="edit_messages")
    )
    
    kb.add(
        InlineKeyboardButton("📊 Бэкап и аналитика", callback_data="files_menu"),
        InlineKeyboardButton("⚙️ Тонкая настройка", callback_data="misc_settings")
    )
    
    kb.add(
        InlineKeyboardButton("📚 Полезные ресурсы", callback_data="links_menu")
    )
    
    bot.send_message(message.chat.id, txt_, parse_mode='HTML', reply_markup=kb)

def files_menu(call: types.CallbackQuery):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
        
    txt_ = """
<b>📁 Работа с файлами</b>

Здесь вы можете управлять файлами плагина, экспортировать данные и очищать историю заказов.
    """.strip()
    
    kb_ = InlineKeyboardMarkup(row_width=2)
    
    kb_.row(
        InlineKeyboardButton("📤 Экспорт файлов", callback_data="export_files"),
        InlineKeyboardButton("📥 Загрузить JSON", callback_data="upload_lots_json")
    )
    
    kb_.row(
        InlineKeyboardButton("📝 Логи ошибок", callback_data="export_errors"),
        InlineKeyboardButton("🗑 Удалить заказы", callback_data="delete_orders")
    )
    
    kb_.add(InlineKeyboardButton("🔙 Вернуться в настройки", callback_data="return_to_settings"))
    
    bot.edit_message_text(txt_, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb_)

def misc_settings(call: types.CallbackQuery):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
        
    cfg = load_config()
    auto_refunds = cfg.get("auto_refunds", True)
    confirm_link = cfg.get("confirm_link", True)
    send_auto_lots = cfg.get("send_auto_lots", True)
    send_auto_lots_interval = cfg.get("send_auto_lots_interval", 30)
    auto_start = cfg.get("auto_start", False)
    
    txt_ = f"""
<b>⚙️ Дополнительные настройки</b>

Здесь вы можете настроить дополнительные параметры работы плагина.

<b>Текущие настройки:</b>
• Автовозвраты: <code>{'Включены ✅' if auto_refunds else 'Выключены ❌'}</code>
• Подтверждение ссылки: <code>{'Включено ✅' if confirm_link else 'Выключено ❌'}</code>
• Отправка файла auto_lots.json: <code>{'Включена ✅' if send_auto_lots else 'Выключена ❌'}</code>
• Интервал отправки (минуты): <code>{send_auto_lots_interval}</code>
• Автозапуск плагина: <code>{'Включен ✅' if auto_start else 'Выключен ❌'}</code>
    """.strip()
    
    kb_ = InlineKeyboardMarkup(row_width=1)
    
    kb_.add(
        InlineKeyboardButton(f"🔄 {'Выключить' if auto_refunds else 'Включить'} автовозвраты", callback_data="toggle_auto_refunds"),
        InlineKeyboardButton(f"✅ {'Выключить' if confirm_link else 'Включить'} подтверждение ссылки", callback_data="toggle_confirm_link")
    )
    
    kb_.add(
        InlineKeyboardButton(f"📤 {'Выключить' if send_auto_lots else 'Включить'} отправку auto_lots.json", callback_data="toggle_send_auto_lots"),
        InlineKeyboardButton("⏱️ Изменить интервал отправки", callback_data="change_send_interval")
    )
    
    kb_.add(
        InlineKeyboardButton(f"🚀 {'Выключить' if auto_start else 'Включить'} автозапуск плагина", callback_data="toggle_auto_start"),
        InlineKeyboardButton("🔄 Обновить номера лотов", callback_data="update_lot_ids")
    )
    
    kb_.add(
        InlineKeyboardButton("🗑 Удалить все лоты", callback_data="delete_all_lots"),
        InlineKeyboardButton("📩 Указать Chat ID для уведомлений", callback_data="set_notification_chat_id")
    )
    
    kb_.add(
        InlineKeyboardButton("🔙 Вернуться в настройки", callback_data="return_to_settings")
    )
    
    bot.edit_message_text(txt_, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb_)

def links_menu(call: types.CallbackQuery):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
        
    txt_ = """
<b>🔗 Полезные ссылки</b>

Здесь вы найдете важные ссылки для работы с плагином и сервисами SMM.
    """.strip()
    
    kb_ = InlineKeyboardMarkup(row_width=2)
    
    kb_.row(
        InlineKeyboardButton("👨‍💻 Разработчик", url="https://t.me/exfador"),
        InlineKeyboardButton("💬 Поддержка", url="https://t.me/terop11")
    )
    
    kb_.row(
        InlineKeyboardButton("🌐 Twiboost", url="https://twiboost.com/ref2613802"),
        InlineKeyboardButton("🌐 Vexboost", url="https://vexboost.ru/ref2874521")
    )
    
    kb_.row(
        InlineKeyboardButton("📣 Канал", url="https://t.me/coxerhub"),
        InlineKeyboardButton("👥 Чат", url="https://t.me/coxerhub_ch")
    )
    
    kb_.add(InlineKeyboardButton("🔙 Вернуться в настройки", callback_data="return_to_settings"))
    
    bot.edit_message_text(txt_, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb_)

def get_statistics():
    if not os.path.exists(ORDERS_PATH):
        return None
    with open(ORDERS_PATH, 'r', encoding='utf-8') as f:
        orders = json.load(f)

    now_ = datetime.now()
    day_ago = now_ - timedelta(days=1)
    week_ago = now_ - timedelta(days=7)
    month_ago = now_ - timedelta(days=30)

    day_orders = [o for o in orders if datetime.strptime(o["date"], "%Y-%m-%d %H:%M:%S") >= day_ago]
    week_orders = [o for o in orders if datetime.strptime(o["date"], "%Y-%m-%d %H:%M:%S") >= week_ago]
    month_orders = [o for o in orders if datetime.strptime(o["date"], "%Y-%m-%d %H:%M:%S") >= month_ago]
    all_orders = orders

    day_total = sum(o["summa"] for o in day_orders)
    week_total = sum(o["summa"] for o in week_orders)
    month_total = sum(o["summa"] for o in month_orders)
    all_total = sum(o["summa"] for o in all_orders)

    day_chistota = sum(o.get("chistota", o["summa"] - o.get("spent", 0)) for o in day_orders)
    week_chistota = sum(o.get("chistota", o["summa"] - o.get("spent", 0)) for o in week_orders)
    month_chistota = sum(o.get("chistota", o["summa"] - o.get("spent", 0)) for o in month_orders)
    all_chistota = sum(o.get("chistota", o["summa"] - o.get("spent", 0)) for o in all_orders)

    return {
        "day_orders": len(day_orders),
        "day_total": day_total,
        "day_chistota": round(day_chistota, 2),
        "week_orders": len(week_orders),
        "week_total": week_total,
        "week_chistota": round(week_chistota, 2),
        "month_orders": len(month_orders),
        "month_total": month_total,
        "month_chistota": round(month_chistota, 2),
        "all_time_orders": len(all_orders),
        "all_time_total": all_total,
        "all_time_chistota": round(all_chistota, 2),
    }

def generate_lots_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    items = list(lot_map.items())

    per_page = 10
    start_ = page * per_page
    end_ = start_ + per_page
    chunk = items[start_:end_]

    kb_ = InlineKeyboardMarkup(row_width=1)
    for lot_key, lot_data in chunk:
        name_ = lot_data["name"]
        sid_ = lot_data["service_id"]
        qty_ = lot_data["quantity"]
        snum_ = lot_data.get("service_number", 1)
        btn_text = f"{name_} [ID={sid_}, Q={qty_}, S={snum_}]"
        cd_ = f"edit_lot_{lot_key}"
        kb_.add(InlineKeyboardButton(btn_text, callback_data=cd_))

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"prev_page_{page-1}"))
    if end_ < len(items):
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"next_page_{page+1}"))
    if nav_buttons:
        kb_.row(*nav_buttons)

    kb_.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
    return kb_

def edit_lot(call: types.CallbackQuery, lot_key: str):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    if lot_key not in lot_map:
        bot.edit_message_text(f"❌ Лот {lot_key} не найден.", call.message.chat.id, call.message.message_id)
        return

    ld_ = lot_map[lot_key]
    txt_ = f"""
<b>{lot_key}</b>
Название: <code>{ld_['name']}</code>
ID услуги: <code>{ld_['service_id']}</code>
Кол-во: <code>{ld_['quantity']}</code>
S#: <code>{ld_.get('service_number', 1)}</code>
""".strip()

    kb_ = InlineKeyboardMarkup(row_width=1)
    kb_.add(
        InlineKeyboardButton("Изменить название", callback_data=f"change_name_{lot_key}"),
        InlineKeyboardButton("Изменить ID услуги", callback_data=f"change_id_{lot_key}"),
        InlineKeyboardButton("Изменить количество", callback_data=f"change_quantity_{lot_key}"),
        InlineKeyboardButton("Изменить сервис#", callback_data=f"change_snum_{lot_key}"),
    )
    kb_.add(InlineKeyboardButton("❌ Удалить лот", callback_data=f"delete_one_lot_{lot_key}"))
    kb_.add(InlineKeyboardButton("◀️ К списку", callback_data="return_to_lots"))
    bot.edit_message_text(txt_, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb_)

def delete_one_lot(call: types.CallbackQuery, lot_key: str):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    if lot_key in lot_map:
        del lot_map[lot_key]
        cfg["lot_mapping"] = lot_map
        reindex_lots(cfg)
        bot.edit_message_text(f"✅ Лот {lot_key} удалён и лоты переиндексированы.", call.message.chat.id, call.message.message_id, reply_markup=generate_lots_keyboard(0))
    else:
        bot.edit_message_text(f"❌ Лот {lot_key} не найден.", call.message.chat.id, call.message.message_id)

def delete_all_lots_func(call: types.CallbackQuery):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
    cfg = load_config()
    preserved_notification_chat_id = cfg.get("notification_chat_id")
    preserved_services = cfg.get("services", {})
    
    new_config = {
        "lot_mapping": {},
        "services": preserved_services,
        "auto_refunds": cfg.get("auto_refunds", True),
        "messages": cfg.get("messages", {}),
        "notification_chat_id": preserved_notification_chat_id
    }
    
    save_config(new_config)
    bot.edit_message_text("✅ Все лоты успешно удалены. Chat ID и сервисы сохранены.", 
                         call.message.chat.id, 
                         call.message.message_id)

def process_name_change(message: types.Message, lot_key: str):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    new_name = message.text.strip()
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    if lot_key not in lot_map:
        bot.send_message(message.chat.id, f"❌ Лот {lot_key} не найден.")
        return
    lot_map[lot_key]["name"] = new_name
    cfg["lot_mapping"] = lot_map
    save_config(cfg)
    kb_ = InlineKeyboardMarkup()
    kb_.add(InlineKeyboardButton("◀️ К лотам", callback_data="return_to_lots"))
    bot.send_message(message.chat.id, f"✅ Название лота {lot_key} изменено на {new_name}.", reply_markup=kb_)

def process_id_change(message: types.Message, lot_key: str):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    try:
        new_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID услуги должно быть числом.")
        return
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    if lot_key not in lot_map:
        bot.send_message(message.chat.id, f"❌ Лот {lot_key} не найден.")
        return
    lot_map[lot_key]["service_id"] = new_id
    cfg["lot_mapping"] = lot_map
    save_config(cfg)
    kb_ = InlineKeyboardMarkup()
    kb_.add(InlineKeyboardButton("◀️ К лотам", callback_data="return_to_lots"))
    bot.send_message(message.chat.id, f"✅ ID услуги для {lot_key} изменён на {new_id}.", reply_markup=kb_)

def process_quantity_change(message: types.Message, lot_key: str):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    try:
        new_q = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: Количество должно быть числом.")
        return
    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})
    if lot_key not in lot_map:
        bot.send_message(message.chat.id, f"❌ Лот {lot_key} не найден.")
        return
    lot_map[lot_key]["quantity"] = new_q
    cfg["lot_mapping"] = lot_map
    save_config(cfg)
    kb_ = InlineKeyboardMarkup()
    kb_.add(InlineKeyboardButton("◀️ К лотам", callback_data="return_to_lots"))
    bot.send_message(message.chat.id, f"✅ Количество для {lot_key} изменено на {new_q}.", reply_markup=kb_)

def process_service_num_change(message: types.Message, lot_key: str):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    try:
        new_snum = int(message.text.strip())
        cfg = load_config()
        if str(new_snum) not in cfg["services"]:
            bot.send_message(message.chat.id, f"❌ Ошибка: Сервис #{new_snum} не существует.")
            return
        lot_map = cfg.get("lot_mapping", {})
        if lot_key not in lot_map:
            bot.send_message(message.chat.id, f"❌ Лот {lot_key} не найден.")
            return
        lot_map[lot_key]["service_number"] = new_snum
        cfg["lot_mapping"] = lot_map
        save_config(cfg)
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("◀️ К лотам", callback_data="return_to_lots"))
        bot.send_message(message.chat.id, f"✅ Номер сервиса для {lot_key} изменён на {new_snum}.", reply_markup=kb_)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: Введите номер сервиса (число).")

def process_new_lot_id_step(message: types.Message):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
    try:
        lot_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка: ID лота должно быть числом.")
        return

    try:
        lot_fields = cardinal_instance.account.get_lot_fields(lot_id)
        fields = lot_fields.fields
        name = fields.get("fields[summary][ru]", "Без названия")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Не удалось получить данные лота: {e}")
        return

    cfg = load_config()
    lot_map = cfg.get("lot_mapping", {})

    new_lot_key = f"lot_{len(lot_map) + 1}"

    lot_map[new_lot_key] = {
        "name": name,
        "service_id": 1,
        "quantity": 1,
        "service_number": 1
    }

    cfg["lot_mapping"] = lot_map
    save_config(cfg)

    kb_ = InlineKeyboardMarkup()
    kb_.add(InlineKeyboardButton("🔙 К настройкам", callback_data="return_to_settings"))
    bot.send_message(message.chat.id, f"✅ Добавлен новый лот {new_lot_key} с названием: {name}", reply_markup=kb_)

def api_settings_menu(call):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
        
    cfg = load_config()
    services = cfg["services"]

    text_ = """
<b>⚙️ Настройки API сервисов SMM</b>

Здесь вы можете настроить подключение к различным SMM-сервисам, 
проверить баланс или добавить новые сервисы.
"""

    for srv_num, srv_data in services.items():
        text_ += f"""
<b>📡 Сервис #{srv_num}</b>
• <b>URL:</b> <code>{srv_data['api_url']}</code>
• <b>API KEY:</b> <code>{srv_data['api_key']}</code>
"""

    kb = InlineKeyboardMarkup(row_width=2)
    
    kb.row(InlineKeyboardButton("📡 API URLs", callback_data="header_no_action"))
    
    api_buttons = []
    for srv_num in services:
        api_buttons.append(InlineKeyboardButton(f"Сервис #{srv_num}", callback_data=f"edit_apiurl_{srv_num}"))
    kb.add(*api_buttons)
    
    kb.row(InlineKeyboardButton("🔑 API Keys", callback_data="header_no_action"))
    
    key_buttons = []
    for srv_num in services:
        key_buttons.append(InlineKeyboardButton(f"Ключ #{srv_num}", callback_data=f"edit_apikey_{srv_num}"))
    kb.add(*key_buttons)
    
    kb.row(InlineKeyboardButton("💰 Балансы сервисов", callback_data="header_no_action"))
    
    balance_buttons = []
    for srv_num in services:
        balance_buttons.append(InlineKeyboardButton(f"Баланс #{srv_num}", callback_data=f"check_balance_{srv_num}"))
    kb.add(*balance_buttons)
    
    kb.row(
        InlineKeyboardButton("➕ Добавить сервис", callback_data="add_service"),
        InlineKeyboardButton("🗑 Удалить сервис", callback_data="delete_service")
    )
    
    kb.add(InlineKeyboardButton("🔙 Вернуться в настройки", callback_data="return_to_settings"))

    bot.edit_message_text(text_, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

def process_apiurl_change(message: types.Message, service_idx: int):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
        
    new_url = message.text.strip()
    
    if not new_url.startswith(("http://", "https://")):
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, "❌ URL должен начинаться с http:// или https://", reply_markup=kb_)
        return
        
    cfg = load_config()
    if str(service_idx) not in cfg["services"]:
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, f"❌ Сервис #{service_idx} не найден в конфигурации.", reply_markup=kb_)
        return
        
    old_url = cfg["services"][str(service_idx)]["api_url"]
    cfg["services"][str(service_idx)]["api_url"] = new_url
    save_config(cfg)
    
    kb_ = InlineKeyboardMarkup(row_width=1)
    kb_.add(
        InlineKeyboardButton("✅ Проверить баланс", callback_data=f"check_balance_{service_idx}"),
        InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings")
    )
    
    text_ = f"""
✅ <b>URL сервиса #{service_idx} успешно обновлен!</b>

• <b>Было:</b> <code>{old_url}</code>
• <b>Стало:</b> <code>{new_url}</code>

Вы можете сразу проверить баланс сервиса для проверки работоспособности.
    """.strip()
    
    bot.send_message(message.chat.id, text_, parse_mode="HTML", reply_markup=kb_)

def process_apikey_change(message: types.Message, service_idx: int):
    if not IS_ACTIVATED:
        bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
        return
        
    new_key = message.text.strip()
    
    if not new_key:
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, "❌ API ключ не может быть пустым", reply_markup=kb_)
        return
        
    cfg = load_config()
    if str(service_idx) not in cfg["services"]:
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, f"❌ Сервис #{service_idx} не найден в конфигурации.", reply_markup=kb_)
        return
    
    old_key = cfg["services"][str(service_idx)]["api_key"]
    old_key_masked = f"{old_key[:4]}...{old_key[-4:]}" if len(old_key) > 8 else old_key
    new_key_masked = f"{new_key[:4]}...{new_key[-4:]}" if len(new_key) > 8 else new_key
    
    cfg["services"][str(service_idx)]["api_key"] = new_key
    save_config(cfg)
    
    kb_ = InlineKeyboardMarkup(row_width=1)
    kb_.add(
        InlineKeyboardButton("✅ Проверить баланс", callback_data=f"check_balance_{service_idx}"),
        InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings")
    )
    
    text_ = f"""
✅ <b>API-ключ сервиса #{service_idx} успешно обновлен!</b>

• <b>Было:</b> <code>{old_key_masked}</code>
• <b>Стало:</b> <code>{new_key_masked}</code>

Вы можете сразу проверить баланс сервиса для проверки работоспособности.
    """.strip()
    
    bot.send_message(message.chat.id, text_, parse_mode="HTML", reply_markup=kb_)

def check_balance_func(call: types.CallbackQuery, service_idx: int):
    if not IS_ACTIVATED:
        bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
        return
        
    cfg = load_config()
    s_ = cfg["services"].get(str(service_idx))
    if not s_:
        bot.edit_message_text(f"❌ Сервис {service_idx} не найден.", call.message.chat.id, call.message.message_id)
        return
        
    bot.edit_message_text(f"⏳ Проверка баланса сервиса #{service_idx}...", 
                         call.message.chat.id, call.message.message_id)
                         
    url_ = f"{s_['api_url']}?action=balance&key={s_['api_key']}"
    
    try:
        rr = requests.get(url_, timeout=10)
        rr.raise_for_status()
        d_ = rr.json()
        bal_ = d_.get("balance", "0")
        

        text_ = f"""
<b>💰 Баланс сервиса #{service_idx}</b>

• <b>Текущий баланс:</b> <code>{bal_}</code>
• <b>Сервис:</b> <code>{s_['api_url'].split('/')[2]}</code>
• <b>Время запроса:</b> <code>{datetime.now().strftime('%H:%M:%S')}</code>
        """.strip()
        
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        
        bot.edit_message_text(text_, call.message.chat.id, call.message.message_id, 
                             parse_mode="HTML", reply_markup=kb_)
                             
    except requests.exceptions.Timeout:
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔄 Повторить", callback_data=f"check_balance_{service_idx}"))
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        
        bot.edit_message_text(f"⚠️ Время ожидания ответа от сервиса #{service_idx} истекло.",
                             call.message.chat.id, call.message.message_id, reply_markup=kb_)
                             
    except Exception as e:
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔄 Повторить", callback_data=f"check_balance_{service_idx}"))
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        
        bot.edit_message_text(f"❌ Ошибка при запросе баланса сервиса #{service_idx}:\n<code>{str(e)[:100]}</code>", 
                             call.message.chat.id, call.message.message_id, 
                             parse_mode="HTML", reply_markup=kb_)

def init_commands(c_: Cardinal):
    global bot, config, lot_mapping, cardinal_instance
    logger.info("=== init_commands() from auto_smm (2 services) ===")

    if IS_ACTIVATED:
        logger.info("Плагин активирован.")
    else:
        logger.warning(f"Плагин не активирован. Ключ: {HASH_MAC}")

    cardinal_instance = c_
    bot = c_.telegram.bot
    
    auto_started = auto_start_plugin(c_)
    if auto_started:
        logger.info("Плагин был автоматически запущен при инициализации")

    @bot.message_handler(content_types=['document'])
    def handle_document_upload(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        user_id = message.from_user.id
        logger.info(f"Получен документ от {user_id}. Проверка ожидания...")
        if user_id not in waiting_for_lots_upload:
            logger.info(f"Пользователь {user_id} не ожидает загрузки JSON")
            bot.send_message(message.chat.id, "❌ Вы не активировали загрузку JSON. Используйте меню настроек.")
            return
        waiting_for_lots_upload.remove(user_id)
        logger.info(f"Пользователь {user_id} удалён из ожидания. Обрабатываю файл...")
        file_id = message.document.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        try:
            data = json.loads(downloaded_file.decode('utf-8'))
            if "lot_mapping" not in data:
                bot.send_message(message.chat.id, "❌ Ошибка: в файле нет ключа 'lot_mapping'.")
                logger.error("JSON не содержит 'lot_mapping'")
                return
            save_config(data)
            kb_ = InlineKeyboardMarkup()
            kb_.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
            bot.send_message(message.chat.id, "✅ Новый auto_lots.json успешно загружен и сохранён!", reply_markup=kb_)
            logger.info("JSON успешно загружен и сохранён")
        except json.JSONDecodeError as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: Не удалось считать JSON. Проверьте синтаксис. ({e})")
            logger.error(f"Ошибка декодирования JSON: {e}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Произошла ошибка при загрузке файла: {e}")
            logger.error(f"Неизвестная ошибка при загрузке: {e}")

    cfg = load_config()
    config.update(cfg)
    lot_mapping.clear()
    lot_mapping.update(cfg.get("lot_mapping", {}))

    drift_mode = bytes([
        0xD0, 0xA0, 0xD0, 0xB0, 0xD0, 0xB7, 0xD1, 0x80, 0xD0, 0xB0, 0xD0, 0xB1, 0xD0, 0xBE, 0xD1, 0x82, 0xD1, 0x87, 0xD0, 0xB8, 0xD0, 0xBA, 0x3A, 0x20, 
        0x40, 0x65, 0x78, 0x66, 0x61, 0x64, 0x6F, 0x72, 0x2C, 0x20, 0xD0, 0xBA, 0xD1, 0x83, 0xD0, 0xBF, 0xD0, 0xB8, 0xD0, 0xBB, 0x20, 0xD1, 0x83, 0x20, 
        0xD0, 0xB4, 0xD1, 0x80, 0xD1, 0x83, 0xD0, 0xB3, 0xD0, 0xBE, 0xD0, 0xB3, 0xD0, 0xBE, 0x3F, 0x20, 0xD1, 0x82, 0xD1, 0x8B, 0x20, 0xD0, 0xB5, 0xD0, 
        0xB1, 0xD0, 0xBB, 0xD0, 0xB0, 0xD0, 0xBD, 0x2C, 0x20, 0xD0, 0xB2, 0xD0, 0xBE, 0xD1, 0x82, 0x20, 0xD0, 0xBE, 0xD1, 0x81, 0xD0, 0xBD, 0xD0, 0xBE, 
        0xD0, 0xB2, 0xD0, 0xBD, 0xD0, 0xBE, 0xD0, 0xB9, 0x20, 0xD0, 0xBA, 0xD0, 0xB0, 0xD0, 0xBD, 0xD0, 0xB0, 0xD0, 0xBB, 0xD0, 0xB0, 0x3A, 0x20, 0x40, 
        0x63, 0x6F, 0x78, 0x65, 0x72, 0x68, 0x75, 0x62
    ])
    mode1 = drift_mode.decode('utf-8')

    logger.info(mode1)
    
    c_.add_telegram_commands(UUID, [
        ("start_smm", "Включить автопродажу", True),
        ("stop_smm", "Выключить автопродажу", True),
        ("auto_smm_settings", "Настройки автопродажи", True),
        ("auto_smm_delete", "Удалить файлы заказов", True)
    ])

    @bot.callback_query_handler(func=lambda call: call.data == "manage_websites")
    def manage_websites(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        valid_links = load_valid_links()
        if valid_links:
            kb_ = InlineKeyboardMarkup(row_width=2)
            for site in valid_links:
                kb_.add(
                    InlineKeyboardButton(site, callback_data=f"delete_website_{site}"),
                    InlineKeyboardButton("Удалить", callback_data=f"delete_website_{site}")
                )
        else:
            kb_ = InlineKeyboardMarkup(row_width=1)
        
        kb_.add(InlineKeyboardButton("➕ Добавить сайт", callback_data="add_website"))
        kb_.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))

        bot.edit_message_text("Список разрешённых сайтов:", call.message.chat.id, call.message.message_id, reply_markup=kb_)

    @bot.callback_query_handler(func=lambda call: call.data == "add_website")
    def add_website_prompt(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text("Введите ссылку для добавления (например, example.com):", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_add_website)

    def process_add_website(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        new_site = message.text.strip()
        add_website(message, new_site)
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 Вернуться в настройки", callback_data="return_to_settings"))
        bot.send_message(message.chat.id, "Вернитесь в настройки для продолжения.", reply_markup=kb_)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_website_"))
    def remove_website_prompt(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        site_to_remove = call.data.split("_", 2)[2]
        valid_links = load_valid_links()
        if site_to_remove in valid_links:
            valid_links.remove(site_to_remove)
            save_valid_links(valid_links)
            bot.edit_message_text(f"✅ Сайт {site_to_remove} удалён из списка.", call.message.chat.id, call.message.message_id)
        else:
            bot.edit_message_text(f"❌ Сайт {site_to_remove} не найден в списке.", call.message.chat.id, call.message.message_id)
        manage_websites(call)

    @bot.callback_query_handler(func=lambda call: call.data == "delete_all_lots")
    def delete_all_lots_prompt(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("Да, удалить", callback_data="confirm_delete_all_lots"),
            InlineKeyboardButton("Нет, отменить", callback_data="return_to_settings")
        )
        bot.edit_message_text("Вы уверены, что хотите удалить все лоты?", call.message.chat.id, call.message.message_id, reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "confirm_delete_all_lots")
    def confirm_delete_all_lots(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        delete_all_lots_func(call)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
        bot.edit_message_text("Все лоты удалены.", call.message.chat.id, call.message.message_id, reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "lot_settings")
    def lot_settings(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔍 Поиск лота", callback_data="search_lot"))
        kb.add(InlineKeyboardButton("📋 Список лотов", callback_data="show_lots_list"))
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
        bot.edit_message_text("Управление лотами:", call.message.chat.id, call.message.message_id, reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "show_lots_list")
    def show_lots_list(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        bot.edit_message_text("Выберите лот:", call.message.chat.id, call.message.message_id, reply_markup=generate_lots_keyboard(0))

    @bot.callback_query_handler(func=lambda call: call.data == "search_lot")
    def search_lot_prompt(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="lot_settings"))
        msg = bot.edit_message_text("Введите название или часть названия лота для поиска:", 
                                    call.message.chat.id, call.message.message_id, reply_markup=kb)
        bot.register_next_step_handler(msg, process_lot_search)

    def process_lot_search(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        search_term = message.text.strip().lower()
        if not search_term:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔙 К настройкам лотов", callback_data="lot_settings"))
            bot.send_message(message.chat.id, "❌ Поисковый запрос не может быть пустым.", reply_markup=kb)
            return
            
        cfg = load_config()
        lot_map = cfg.get("lot_mapping", {})
        
        found_lots = {}
        for lot_key, lot_data in lot_map.items():
            lot_name = lot_data["name"].lower()
            if search_term in lot_name:
                found_lots[lot_key] = lot_data
                
        if not found_lots:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔍 Новый поиск", callback_data="search_lot"))
            kb.add(InlineKeyboardButton("🔙 К настройкам лотов", callback_data="lot_settings"))
            bot.send_message(message.chat.id, f"❌ Лоты с названием '{search_term}' не найдены.", reply_markup=kb)
            return
            
        kb = InlineKeyboardMarkup(row_width=1)
        for lot_key, lot_data in found_lots.items():
            name_ = lot_data["name"]
            sid_ = lot_data["service_id"]
            qty_ = lot_data["quantity"]
            snum_ = lot_data.get("service_number", 1)
            btn_text = f"{name_} [ID={sid_}, Q={qty_}, S={snum_}]"
            cd_ = f"edit_lot_{lot_key}"
            kb.add(InlineKeyboardButton(btn_text, callback_data=cd_))
            
        kb.add(InlineKeyboardButton("🔍 Новый поиск", callback_data="search_lot"))
        kb.add(InlineKeyboardButton("🔙 К настройкам лотов", callback_data="lot_settings"))
        bot.send_message(message.chat.id, f"🔍 Результаты поиска для '{search_term}':", reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_lot_"))
    def edit_lot_callback(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 2)[2]
        edit_lot(call, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("prev_page_") or call.data.startswith("next_page_"))
    def page_navigation(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        try:
            page_ = int(call.data.split("_")[-1])
        except ValueError:
            page_ = 0
        bot.edit_message_text("Выберите лот:", call.message.chat.id, call.message.message_id, reply_markup=generate_lots_keyboard(page_))

    @bot.callback_query_handler(func=lambda call: call.data == "show_orders")
    def show_orders(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        stats = get_statistics()
        if not stats:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
            bot.edit_message_text("❌ Нет данных о заказах.", call.message.chat.id, call.message.message_id, reply_markup=kb)
            return

        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))

        text = f"""
📊 <b>Информация о заказах SMM</b>

За 24 часа: {stats['day_orders']} заказов на {stats['day_total']} руб. (чистая прибыль: {stats['day_chistota']} руб.)
За неделю: {stats['week_orders']} заказов на {stats['week_total']} руб. (чистая прибыль: {stats['week_chistota']} руб.)
За месяц: {stats['month_orders']} заказов на {stats['month_total']} руб. (чистая прибыль: {stats['month_chistota']} руб.)
За всё время: {stats['all_time_orders']} заказов на {stats['all_time_total']} руб. (чистая прибыль: {stats['all_time_chistota']} руб.)
        """.strip()

        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "upload_lots_json")
    def upload_lots_json(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        user_id = call.from_user.id
        waiting_for_lots_upload.add(user_id)
        logger.info(f"Добавлен пользователь {user_id} в waiting_for_lots_upload: {waiting_for_lots_upload}")
        bot.edit_message_text("Пришлите файл JSON (можно любым названием).", call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "export_files")
    def export_files(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        chat_id_ = call.message.chat.id
        files_to_send = [CONFIG_PATH, ORDERS_PATH, ORDERS_DATA_PATH]
        for f_ in files_to_send:
            if os.path.exists(f_):
                try:
                    with open(f_, 'rb') as ff:
                        bot.send_document(chat_id_, ff, caption=f"Файл: {os.path.basename(f_)}")
                except Exception as e:
                    bot.edit_message_text(f"Ошибка отправки {f_}: {e}", chat_id_, call.message.message_id)
            else:
                bot.edit_message_text(f"Файл не найден: {f_}", chat_id_, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "export_errors")
    def export_errors(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        chat_id_ = call.message.chat.id
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, 'rb') as f:
                    bot.send_document(chat_id_, f, caption="Лог ошибок")
                bot.edit_message_text("Логи выгружены.", chat_id_, call.message.message_id)
            except Exception as e:
                bot.edit_message_text(f"Ошибка отправки лог-файла: {e}", chat_id_, call.message.message_id)
        else:
            bot.edit_message_text("Лог-файл не найден.", chat_id_, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "delete_orders")
    def delete_orders(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        if os.path.exists(ORDERS_PATH):
            os.remove(ORDERS_PATH)
        if os.path.exists(ORDERS_DATA_PATH):
            os.remove(ORDERS_DATA_PATH)
        bot.edit_message_text("Файлы заказов удалены.", call.message.chat.id, call.message.message_id)
        files_menu(call)

    @bot.callback_query_handler(func=lambda call: call.data == "toggle_auto_refunds")
    def toggle_auto_refunds(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        ar_ = cfg.get("auto_refunds", True)
        cfg["auto_refunds"] = not ar_
        save_config(cfg)
        bot.answer_callback_query(call.id, f"✅ Автовозвраты: {'ВКЛ' if cfg['auto_refunds'] else 'ВЫКЛ'}")
        misc_settings(call)

    @bot.callback_query_handler(func=lambda call: call.data == "toggle_confirm_link")
    def toggle_confirm_link(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        confirm_link = cfg.get("confirm_link", True)
        cfg["confirm_link"] = not confirm_link
        save_config(cfg)
        bot.answer_callback_query(call.id, f"✅ Подтверждение ссылки: {'ВКЛ' if cfg['confirm_link'] else 'ВЫКЛ'}")
        misc_settings(call)

    @bot.callback_query_handler(func=lambda call: call.data == "toggle_send_auto_lots")
    def toggle_send_auto_lots(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        current_value = cfg.get("send_auto_lots", True)
        cfg["send_auto_lots"] = not current_value
        save_config(cfg)
        bot.answer_callback_query(call.id, f"Отправка auto_lots.json {'отключена' if current_value else 'включена'}!")
        misc_settings(call)
        
    @bot.callback_query_handler(func=lambda call: call.data == "toggle_auto_start")
    def toggle_auto_start(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                              call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        current_value = cfg.get("auto_start", False)
        cfg["auto_start"] = not current_value
        save_config(cfg)
        bot.answer_callback_query(call.id, f"Автозапуск плагина {'отключен' if current_value else 'включен'}!")
        misc_settings(call)

    @bot.callback_query_handler(func=lambda call: call.data == "change_send_interval")
    def change_send_interval(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        current_interval = cfg.get("send_auto_lots_interval", 30)
        
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 Вернуться назад", callback_data="cancel_interval_change"))
        
        msg_ = bot.edit_message_text(f"Текущий интервал отправки: {current_interval} минут\n\nВведите новый интервал отправки auto_lots.json в минутах (от 5 до 1440):", 
                                call.message.chat.id, call.message.message_id, reply_markup=kb_)
        bot.register_next_step_handler(msg_, process_send_interval_change)

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_interval_change")
    def cancel_interval_change(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                call.message.chat.id, call.message.message_id)
            return
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        misc_settings(call)
    
    def process_send_interval_change(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        try:
            new_interval = int(message.text.strip())
            if new_interval < 5:
                bot.send_message(message.chat.id, "❌ Интервал не может быть меньше 5 минут")
                return
            if new_interval > 1440:
                bot.send_message(message.chat.id, "❌ Интервал не может быть больше 1440 минут (24 часа)")
                return
                
            cfg = load_config()
            cfg["send_auto_lots_interval"] = new_interval
            save_config(cfg)
            
            kb_ = InlineKeyboardMarkup()
            kb_.add(InlineKeyboardButton("🔙 К настройкам", callback_data="misc_settings"))
            bot.send_message(message.chat.id, f"✅ Интервал отправки auto_lots.json установлен: {new_interval} минут", reply_markup=kb_)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Ошибка: Введите корректное число минут.")
            
    @bot.callback_query_handler(func=lambda call: call.data == "return_to_settings")
    def return_to_settings(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        
        cfg = load_config()
        lmap = cfg.get("lot_mapping", {})
        auto_refunds = cfg.get("auto_refunds", True)
        confirm_link = cfg.get("confirm_link", True)
        notif_chat_id = cfg.get("notification_chat_id", "Не задан")
        send_auto_lots = cfg.get("send_auto_lots", True)
        send_auto_lots_interval = cfg.get("send_auto_lots_interval", 30)
        auto_start = cfg.get("auto_start", False)

        status_text = "✅ АКТИВИРОВАН" if IS_ACTIVATED else f"❌ НЕ АКТИВИРОВАН (Ключ: {HASH_MAC})"

        txt_ = f"""
🚀 <b>AUTOSMM ПАНЕЛЬ УПРАВЛЕНИЯ v{VERSION}</b> 🚀
━━━━━━━━━━━━━━━━━━━━━━━━
👨‍💻 <b>Разработчик:</b> {CREDITS}

📊 <b>СТАТУС:</b> {status_text}

💡 <b>ОСНОВНЫЕ ПАРАМЕТРЫ:</b>
 • Лотов в базе: <code>{len(lmap)}</code>
 • Автовозвраты: {'✅' if auto_refunds else '❌'}
 • Подтверждение ссылки: {'✅' if confirm_link else '❌'}
 • Отправка auto_lots.json: {'✅' if send_auto_lots else '❌'}
 • Интервал отправки: <code>{send_auto_lots_interval} мин</code>
 • Автозапуск: {'✅' if auto_start else '❌'}

📞 <b>УВЕДОМЛЕНИЯ:</b> <code>{notif_chat_id}</code>

📝 <b>О ПЛАГИНЕ:</b> <i>{DESCRIPTION}</i>
━━━━━━━━━━━━━━━━━━━━━━━━
    """.strip()

        kb = InlineKeyboardMarkup(row_width=2)
        
        kb.add(
            InlineKeyboardButton("🛍️ Каталог лотов", callback_data="lot_settings"),
            InlineKeyboardButton("➕ Создать новый лот", callback_data="add_new_lot")
        )
        
        kb.add(
            InlineKeyboardButton("🔌 Интеграция API", callback_data="api_settings"),
        )
        
        kb.add(
            InlineKeyboardButton("🌐 Доверенные сайты", callback_data="manage_websites"),
            InlineKeyboardButton("💬 Шаблоны сообщений", callback_data="edit_messages")
        )
        
        kb.add(
            InlineKeyboardButton("📊 Бэкап и аналитика", callback_data="files_menu"),
            InlineKeyboardButton("⚙️ Тонкая настройка", callback_data="misc_settings")
        )
        
        kb.add(
            InlineKeyboardButton("📚 Полезные ресурсы", callback_data="links_menu")
        )

        bot.edit_message_text(txt_, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "return_to_lots")
    def return_to_lots(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        bot.edit_message_text("Выберите лот:", call.message.chat.id, call.message.message_id, reply_markup=generate_lots_keyboard(0))

    @bot.callback_query_handler(func=lambda call: call.data.startswith("change_name_"))
    def change_name(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 2)[2]
        msg_ = bot.edit_message_text(f"Введите новое название для {lot_key}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_name_change, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("change_id_"))
    def change_id(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 2)[2]
        msg_ = bot.edit_message_text(f"Введите новый ID услуги для {lot_key}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_id_change, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("change_quantity_"))
    def change_quantity(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 2)[2]
        msg_ = bot.edit_message_text(f"Введите новое количество для {lot_key}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_quantity_change, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("change_snum_"))
    def change_snum(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 2)[2]
        msg_ = bot.edit_message_text(f"Введите номер сервиса для {lot_key}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_service_num_change, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_one_lot_"))
    def delete_one_lot_callback(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        lot_key = call.data.split("_", 3)[3]
        delete_one_lot(call, lot_key)

    @bot.callback_query_handler(func=lambda call: call.data == "api_settings")
    def api_settings_callback(call: types.CallbackQuery):
        api_settings_menu(call)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_apiurl_"))
    def edit_apiurl(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        idx_ = int(call.data.split("_")[-1])
        msg_ = bot.edit_message_text(f"Введите новый URL для сервиса #{idx_}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_apiurl_change, idx_)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_apikey_"))
    def edit_apikey(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        idx_ = int(call.data.split("_")[-1])
        msg_ = bot.edit_message_text(f"Введите новый ключ для сервиса #{idx_}:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_apikey_change, idx_)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("check_balance_"))
    def check_balance(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        idx_ = int(call.data.split("_")[-1])
        check_balance_func(call, idx_)

    @bot.callback_query_handler(func=lambda call: call.data == "add_new_lot")
    def add_new_lot(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg_ = bot.send_message(call.message.chat.id, "Введите ID лота для добавления:")
        bot.register_next_step_handler(msg_, process_new_lot_id_step)

    @bot.callback_query_handler(func=lambda call: call.data == "update_lot_ids")
    def update_lot_ids(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        reindex_lots(cfg)
        bot.answer_callback_query(call.id, "Номера лотов обновлены.")
        misc_settings(call)

    @bot.callback_query_handler(func=lambda call: call.data == "edit_messages")
    def edit_messages_menu(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        cfg = load_config()
        msg_payment = cfg["messages"]["after_payment"]
        msg_confirmation = cfg["messages"]["after_confirmation"]

        text_ = f"""
⚙ <b>Редактирование текстов сообщений</b>

<b>После оплаты:</b>

Переменные: https://teletype.in/@exfador/kT9IpmDNovR

<code>{msg_payment}</code>

<b>После подтверждения ссылки:</b>

Переменные: https://teletype.in/@exfador/kT9IpmDNovR

<code>{msg_confirmation}</code>
        """.strip()

        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("Изменить текст после оплаты", callback_data="edit_msg_payment"),
            InlineKeyboardButton("Изменить текст после подтверждения", callback_data="edit_msg_confirmation")
        )
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))

        bot.edit_message_text(text_, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "edit_msg_payment")
    def edit_msg_payment(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text("Введите новый текст после оплаты:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_message_payment_change)

    @bot.callback_query_handler(func=lambda call: call.data == "edit_msg_confirmation")
    def edit_msg_confirmation(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text("Введите новый текст после подтверждения:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_message_confirmation_change)

    def process_message_payment_change(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        new_text = message.text.strip()
        cfg = load_config()
        cfg["messages"]["after_payment"] = new_text
        save_config(cfg)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
        bot.send_message(message.chat.id, "Текст после оплаты обновлен.", reply_markup=kb)

    def process_message_confirmation_change(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        new_text = message.text.strip()
        cfg = load_config()
        cfg["messages"]["after_confirmation"] = new_text
        save_config(cfg)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Назад", callback_data="return_to_settings"))
        bot.send_message(message.chat.id, "Текст после подтверждения обновлен.", reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "add_service")
    def add_service(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text("Введите номер нового сервиса (число):", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_add_service)

    @bot.callback_query_handler(func=lambda call: call.data == "delete_service")
    def delete_service(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text("Введите номер сервиса для удаления:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_delete_service)

    def process_add_service(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        try:
            srv_num = int(message.text.strip())
            if srv_num < 1:
                raise ValueError
        except ValueError:
            bot.send_message(message.chat.id, "❌ Ошибка: Номер сервиса должен быть положительным числом.")
            return

        cfg = load_config()
        if str(srv_num) in cfg["services"]:
            bot.send_message(message.chat.id, f"❌ Сервис #{srv_num} уже существует.")
            return

        cfg["services"][str(srv_num)] = {
            "api_url": "https://example.com/api/v2",
            "api_key": "YOUR_API_KEY"
        }
        save_config(cfg)
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, f"✅ Сервис #{srv_num} добавлен. Настройте его URL и ключ.", reply_markup=kb_)

    def process_delete_service(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        try:
            srv_num = int(message.text.strip())
        except ValueError:
            bot.send_message(message.chat.id, "❌ Ошибка: Номер сервиса должен быть числом.")
            return

        cfg = load_config()
        if str(srv_num) not in cfg["services"]:
            bot.send_message(message.chat.id, f"❌ Сервис #{srv_num} не существует.")
            return

        del cfg["services"][str(srv_num)]
        save_config(cfg)
        kb_ = InlineKeyboardMarkup()
        kb_.add(InlineKeyboardButton("🔙 К настройкам API", callback_data="api_settings"))
        bot.send_message(message.chat.id, f"✅ Сервис #{srv_num} удален.", reply_markup=kb_)

    @bot.callback_query_handler(func=lambda call: call.data == "set_notification_chat_id")
    def set_notification_chat_id(call: types.CallbackQuery):
        if not IS_ACTIVATED:
            bot.edit_message_text(f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.", 
                                  call.message.chat.id, call.message.message_id)
            return
        msg_ = bot.edit_message_text(f"Введите Chat ID для уведомлений (например, -1001234567890 для группы или ваш ID, ваш id: {call.message.chat.id}):", 
                                    call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(msg_, process_notification_chat_id)

    def process_notification_chat_id(message: types.Message):
        if not IS_ACTIVATED:
            bot.send_message(message.chat.id, f"❌ Плагин не активирован. Ваш ключ: {HASH_MAC} Обратитесь @exfador или @terop11 для активации.")
            return
        try:
            new_chat_id = int(message.text.strip())
            cfg = load_config()
            cfg["notification_chat_id"] = new_chat_id
            save_config(cfg)
            kb_ = InlineKeyboardMarkup()
            kb_.add(InlineKeyboardButton("🔙 К настройкам", callback_data="return_to_settings"))
            bot.send_message(message.chat.id, f"✅ Chat ID для уведомлений установлен: {new_chat_id}", reply_markup=kb_)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Ошибка: Введите корректный Chat ID (целое число).")

    @bot.callback_query_handler(func=lambda call: call.data == "files_menu")
    def files_menu_callback(call: types.CallbackQuery):
        files_menu(call)

    @bot.callback_query_handler(func=lambda call: call.data == "misc_settings")
    def misc_settings_callback(call: types.CallbackQuery):
        misc_settings(call)

    @bot.callback_query_handler(func=lambda call: call.data == "links_menu")
    def links_menu_callback(call: types.CallbackQuery):
        links_menu(call)

    c_.telegram.msg_handler(start_smm, commands=["start_smm"])
    c_.telegram.msg_handler(stop_smm, commands=["stop_smm"])
    c_.telegram.msg_handler(auto_smm_settings, commands=["auto_smm_settings"])
    c_.telegram.msg_handler(auto_smm_delete, commands=["auto_smm_delete"])

BIND_TO_PRE_INIT = [init_commands]
BIND_TO_NEW_MESSAGE = [auto_smm_handler]
BIND_TO_NEW_ORDER = [auto_smm_handler]
BIND_TO_DELETE = None

def start_order_checking_if_needed(c: Cardinal):
    if RUNNING and IS_ACTIVATED:  
        start_order_checking(c)

def send_order_started_notification(c: Cardinal, order_id_funpay: str, twiboost_id: int, link: str, api_url: str, api_key: str, lot_price: float, real_amount: int):
    """
    Отправляет уведомление о начале заказа с информацией о чистой прибыли
    """
    cfg = load_config()
    notification_chat_id = cfg.get("notification_chat_id")
    if not notification_chat_id:
        logger.warning("Notification chat_id не задан в конфигурации.")
        return
        
    try:
        status_url = f"{api_url}?action=status&order={twiboost_id}&key={api_key}"
        status_resp = requests.get(status_url, timeout=10)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        
        charge = float(status_data.get("charge", "0"))
        currency = status_data.get("currency", "USD")
        
        net_profit = round(lot_price - charge, 2)

        
        order_data = c.account.get_order(order_id_funpay)
        buyer_username = order_data.buyer_username
        
        kb_ = InlineKeyboardMarkup()
        order_url = f"https://funpay.com/orders/{order_id_funpay}/"
        kb_.add(InlineKeyboardButton("Перейти к заказу", url=order_url))
        
        notification_text = (
            f"🚀 [AUTOSMM] Заказ #{order_id_funpay} начат!\n\n"
            f"👤 Покупатель: {buyer_username}\n"
            f"🔢 ID заказа: {order_id_funpay}\n"
            f"💰 Сумма на FP: {lot_price} ₽\n"
            f"💸 Сумма на сайте: {charge} {currency}\n"
            f"✅ Чистая прибыль: {net_profit} ₽\n"
            f"🔢 Кол-во: {real_amount}\n"
            f"🔗 Ссылка: {link}"
        )
        
        c.telegram.bot.send_message(
            notification_chat_id,
            notification_text,
            reply_markup=kb_
        )
        
    except Exception as ex:
        logger.error(f"Ошибка при отправке уведомления о начале заказа: {ex}")

def process_link_without_confirmation(c: Cardinal, data: Dict):
    """
    Обрабатывает ссылку без подтверждения или после получения подтверждения.
    """
    link_ = data["link"]
    service_id = data["service_id"]
    real_amount = data["real_amount"]
    order_id_funpay = data["order_id_funpay"]
    buyer_chat_id = data["chat_id"]
    service_number = data["service_number"]
    lot_price = data["price"]
    
    cfg = load_config()
    service_cfg = cfg["services"].get(str(service_number))
    if not service_cfg:
        logger.error(f"Нет настроек для service_number={service_number}")
        c.send_message(buyer_chat_id, f"❌ Ошибка: нет настроек для service_number={service_number}.")
        refund_order(c, order_id_funpay, buyer_chat_id, 
                    reason="Ошибка конфигурации.",
                    detailed_reason=f"Нет настроек для service_number={service_number}.")
        return
    api_url = service_cfg["api_url"]
    api_key = service_cfg["api_key"]
    encoded_link = quote(link_, safe="")
    url_req = f"{api_url}?action=add&service={service_id}&link={encoded_link}&quantity={real_amount}&key={api_key}"

    try:
        resp_ = requests.get(url_req)
        resp_.raise_for_status()
        j_ = resp_.json()
        if "order" in j_:
            twiboost_id = j_["order"]
            chistota = float(lot_price)
            
            save_order_data(
                buyer_chat_id,
                order_id_funpay,
                twiboost_id,
                "pending",
                chistota,
                link_,
                real_amount,
                service_number
            )
            
            send_order_started_notification(
                c, 
                order_id_funpay, 
                twiboost_id, 
                link_, 
                api_url, 
                api_key, 
                lot_price, 
                real_amount
            )
            
            check_order_status(c, twiboost_id, buyer_chat_id, link_, order_id_funpay)

            msg_confirmation = cfg["messages"]["after_confirmation"].format(
                twiboost_id=twiboost_id,
                link=link_
            )
            c.send_message(buyer_chat_id, msg_confirmation)
            waiting_for_link.pop(str(order_id_funpay), None)
        else:
            logger.error(f"Нет 'order' в ответе: {j_}")
            refund_order(
                c,
                order_id_funpay,
                buyer_chat_id,
                reason="Ошибка при создании заказа.",
                detailed_reason=f"Ошибка при создании заказа: нет 'order' в ответе API. Ответ: {j_}"
            )

    except requests.exceptions.RequestException as req_ex:
        logger.error(f"Ошибка сети при создании заказа #{order_id_funpay}: {req_ex}")
        refund_order(
            c,
            order_id_funpay,
            buyer_chat_id,
            reason="Сетевая ошибка.",
            detailed_reason=f"Сетевая ошибка при создании заказа: {req_ex}"
        )
    except ValueError as val_ex:
        logger.error(f"ValueError при обработке ответа заказа #{order_id_funpay}: {val_ex}")
        refund_order(
            c,
            order_id_funpay,
            buyer_chat_id,
            reason="Неверный формат данных.",
            detailed_reason=f"Неверный формат данных от API: {val_ex}"
        )
    except Exception as ex:
        logger.error(f"Неизвестная ошибка при создании заказа #{order_id_funpay}: {ex}")
        refund_order(
            c,
            order_id_funpay,
            buyer_chat_id,
            reason="Неизвестная ошибка.",
            detailed_reason=f"Неизвестная ошибка при создании заказа: {ex}"
        )

def start_auto_lots_sender(c: Cardinal):
    """
    Отправляет файл auto_lots.json на заданный chat_id с заданной периодичностью
    """
    global RUNNING
    
    logger.info("Запуск потока отправки auto_lots.json")
    
    while RUNNING:
        try:
            cfg = load_config()
            chat_id = cfg.get("notification_chat_id")
            send_auto_lots = cfg.get("send_auto_lots", True)
            interval_minutes = cfg.get("send_auto_lots_interval", 30)
            
            if chat_id and send_auto_lots and os.path.exists(CONFIG_PATH):
                if c.telegram and c.telegram.bot:
                    try:
                        with open(CONFIG_PATH, 'rb') as file:
                            c.telegram.bot.send_document(
                                chat_id, 
                                file, 
                                caption=f"📄 Автоматическая отправка файла auto_lots.json\n\n⏱️ Следующая отправка через {interval_minutes} минут"
                            )
                            logger.info(f"Файл auto_lots.json отправлен на chat_id {chat_id}")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке auto_lots.json: {e}")
            
            wait_time = interval_minutes * 60
            sleep_interval = 1
            
            for _ in range(wait_time):
                if not RUNNING:
                    break
                time.sleep(sleep_interval)
                
        except Exception as e:
            logger.error(f"Ошибка в потоке отправки auto_lots.json: {e}")
            time.sleep(60)

def auto_start_plugin(c: Cardinal):
    """
    Автоматический запуск плагина на основе настройки auto_start
    """
    if not IS_ACTIVATED:
        logger.warning(f"Плагин не активирован, автозапуск невозможен. Ключ: {HASH_MAC}")
        return False
        
    cfg = load_config()
    auto_start = cfg.get("auto_start", False)
    
    if auto_start:
        logger.info("Автоматический запуск плагина SMM")
        global RUNNING, IS_STARTED, ORDER_CHECK_THREAD, AUTO_LOTS_SEND_THREAD
        RUNNING = True
        IS_STARTED = True
    
        if not ORDER_CHECK_THREAD or not ORDER_CHECK_THREAD.is_alive():
            ORDER_CHECK_THREAD = threading.Thread(target=start_order_checking, args=(c,))
            ORDER_CHECK_THREAD.daemon = True
            ORDER_CHECK_THREAD.start()
        
        if not AUTO_LOTS_SEND_THREAD or not AUTO_LOTS_SEND_THREAD.is_alive():
            AUTO_LOTS_SEND_THREAD = threading.Thread(target=start_auto_lots_sender, args=(c,))
            AUTO_LOTS_SEND_THREAD.daemon = True
            AUTO_LOTS_SEND_THREAD.start()
            
        logger.info("Плагин SMM успешно запущен автоматически")
        return True
    
    return False
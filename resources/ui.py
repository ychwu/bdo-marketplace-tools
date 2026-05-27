import os
from colorama import Fore, Style
import asyncio
import random
from getpass import getpass
from resources.credentials import (
    CredentialStoreError,
    load_credentials,
    save_credentials,
)

class mainMenu():
    def __init__(self, task_manager, api_handler):
        self.main_art = r"""
 ___ ___   ____  ____   __  _    ___ ______       _____ ____   ____  ____   ___  ____  
|   |   | /    ||    \ |  |/ ]  /  _]      |     / ___/|    \ |    ||    \ /  _]|    \ 
| _   _ ||  o  ||  D  )|  ' /  /  [_|      |    (   \_ |  _  | |  | |  o  )  [_ |  D  )
|  \_/  ||     ||    / |    \ |    _]_|  |_|     \__  ||  |  | |  | |   _/    _]|    / 
|   |   ||  _  ||    \ |     \|   [_  |  |       /  \ ||  |  | |  | |  | |   [_ |    \ 
|   |   ||  |  ||  .  \|  .  ||     | |  |       \    ||  |  | |  | |  | |     ||  .  \
|___|___||__|__||__|\_||__|\_||_____| |__|        \___||__|__||____||__| |_____||__|\_|
                                                                                       
                            @@@@@@@@@@@@@@@                         
                       @@@@@@@@@@@@@@@@@@@@@@@@.                      
                     @@@@@@@@@@@@@   @@@@@@@@@@@@@                    
                   @@@@@@@@@@@@@    @  &@@@@@@@@@@@                   
                  @@@@@@@@@@@@   @   @   @@@@@@@@@@@@                 
                 @@@@@@@@@@@@@@@@     @@@@@@@@@@@@@@@@                
                ,@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@                
                @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@               
               %@@@@@@@@  @@@@@@@@@@@@@@@@@@@  @@@@@@@@&              
               @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@              
              @@@@@@@@@@@@@@@@@@@@   @@@@@@@@@@@@@@@@@@@,             
              @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@             
              @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@             
              @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@             
               @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@,              
                 @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@%                
                   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@                  
                      @@@@@@@@@@@@@@@@@@@@@@@@@@@
"""
        self.main_menu = {
            "1": "Set up Login Credentials",
            "2": "Login",
            "3": "Enable sniper",
            "4": "Disable sniper",
            "5": "Set Delay",
            "6": "Exit",
            "7": "MP Inventory [TESTING ONLY]"
        }
        self.task_manager = task_manager
        self.api_handler = api_handler
        self.loginMenu = loginMenu(api_handler)
        self.choices = {
            "1": self.loginMenu.run,
            "2": self.task_manager.login,
            "3": self.task_manager.start_checker,
            "4": self.task_manager.stop_checker,
            "5": self.task_manager.set_delay,
            "6": self.exit,
            "7": self.mp_inventory
        }



    # Display the main menu
    async def display_menu(self):
        print(self.main_art)
        print("Welcome to the BDO Marketplace Sniper [" + Fore.GREEN + "BETA" + Style.RESET_ALL + "]")
        print()
        print(await self.load_credentials())
        print(await self.login_status())
        print(await self.sniper_status())
        print(await self.current_delay())
        print()
        for key, value in self.main_menu.items():
            print(f"{key}. {value}")
    
    # Run the main menu
    async def run(self):
        while True:
            await self.display_menu()
            choice = await asyncio.to_thread(input, "Enter your choice: ")
            action = self.choices.get(choice)
            if action:
                await action()
            else:
                print(f"{choice} is not a valid choice.")

    # Check and return the login status
    async def login_status(self):
        return await self.task_manager.check_login_status()
    
    # Check and return the sniper status
    async def sniper_status(self):
        return await self.task_manager.checker_status()
    
    # Load credentials
    async def load_credentials(self):
        try:
            email, password = load_credentials()
        except CredentialStoreError as exc:
            return ("Credential Status:    " + Fore.RED + str(exc) + Style.RESET_ALL)

        if email and password:
            self.api_handler.email = email
            self.api_handler.password = password
            return ("Credential Status:    " + Fore.GREEN + "Set" + Style.RESET_ALL)
        elif email:
            self.api_handler.email = email
            self.api_handler.password = None
            return ("Credential Status:    " + Fore.RED + "Password Not Set" + Style.RESET_ALL)
        else:
            return ("Credential Status:    " + Fore.RED + "Not Set" + Style.RESET_ALL)


    async def current_delay(self):
        return ("Current delay:        [" + self.task_manager.delay_choices[self.task_manager.delay][0] + "]")

    async def mp_inventory(self):
        r = await self.api_handler.get_mp_inventory()
        print(r)

    
    # Exit the program
    async def exit(self):
        await self.task_manager.stop_checker()
        print("Exiting the program.")
        self.api_handler.save_session()
        exit(0)


class loginMenu():
    def __init__(self, api_handler):
        self.login_menu = {
            "1": "Set Email",
            "2": "Set Password",
            "3": "Back to main menu"
        }
        self.choices = {
            "1": self.get_email, 
            "2": self.get_password,
            "3": self.back_to_main
        }

        self.api_handler = api_handler
        self.email = None
        self.password = None
      
    # Display the login menu
    async def display_menu(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("Login to the BDO Marketplace Sniper")
        for key, value in self.login_menu.items():
            print(f"{key}. {value}")
    
    # Run the login menu
    async def run(self):
        while True:
            await self.display_menu()
            choice = await asyncio.to_thread(input, "Enter your choice: ")
            action = self.choices.get(choice)
            if action:
                if await action() == "back": # if back is selected, break the loop and return to main menu
                    break
            else:
                print(f"{choice} is not a valid choice.")
    
    # Return "back" when back is selected
    async def back_to_main(self):
        return "back"
    
    # Get the email from the user
    async def get_email(self):
        email = await asyncio.to_thread(input, "Enter your email: ")
        self.email = email
        self.api_handler.email = email
        try:
            save_credentials(email)
        except CredentialStoreError as exc:
            print(f"Unable to save email: {exc}")
    
    # Get the password from the user
    async def get_password(self):
        if not self.email:
            self.email = self.api_handler.email

        if not self.email:
            print("Please set your email first.")
            return

        password = await asyncio.to_thread(getpass, "Enter your password: ")
        self.password = password
        self.api_handler.password = password
        try:
            save_credentials(self.email, password)
        except CredentialStoreError as exc:
            print(f"Unable to save password: {exc}")

class backgroundTasks():
    def __init__(self, api_handler):
        self.api_handler = api_handler
        self.checker_task = None
        self.checker_enabled = False
        self.delay_choices = {
            "1": ("Ludicrous", (3, 5)),
            "2": ("Moderate", (5, 10)),
            "3": ("Slow", (15, 30))
        }
        self.delay = "3"

    # Start the sniper
    async def start_checker(self):
        if self.api_handler.login_status:
            if self.checker_task is None or self.checker_task.done():
                self.checker_task = asyncio.create_task(self.checker())
                print("Checker started.")
                self.checker_enabled = True
            else:
                print("Checker is already running.")
        else:
            print("Please login first.")

    # Stop the sniper
    async def stop_checker(self):
        if self.checker_task and not self.checker_task.cancelled():
            self.checker_task.cancel()
            print("Checker stopped.")
            self.checker_enabled = False
        else:
            print("Checker is not running.")
        
        self.checker_task = None
    
    # Check the status of the sniper
    async def checker_status(self):
        if self.checker_enabled:
            return ("Sniper Status:        " + Fore.GREEN + "Running" + Style.RESET_ALL)
        else:
            return ("Sniper Status:        " + Fore.RED + "Stopped" + Style.RESET_ALL)

    # Main process of the sniper
    async def checker(self):
        while True:
            buyList = await self.api_handler.check_stock() # CHANGE THIS to check_stock_test() for testing
            if buyList:
                print("Item in stock. Attempting to buy.....")
                await self.buy_item(buyList)
            else:
                None # This is a testing statement only
            
            sleep_duration = random.uniform(*self.delay_choices[self.delay][1])
            await asyncio.sleep(sleep_duration)
            
    
    # Check Login Status
    async def check_login_status(self):
        if self.api_handler.login_status:
            return ("Login Status:         " + Fore.GREEN + "Logged in" + Style.RESET_ALL)
        else:
            return ("Login Status:         " + Fore.RED + "Not logged in" + Style.RESET_ALL)
    

    # Check credentials
    async def check_credentials(self):
        if self.api_handler.email and self.api_handler.password:
            return ("Credential Status:    " + Fore.GREEN + "Set" + Style.RESET_ALL)
        else:
            return ("Credential Status:    " + Fore.RED + "Not Set" + Style.RESET_ALL)
    
    # Buy the item
    async def buy_item(self, buyList):
        # buylist is of format [(item_id, stock, price), ...]

        updated_buyList = await self.price_calc(buyList)
        await self.api_handler.buy_item(updated_buyList)
    

    # Update the price to the maximum price
    async def price_calc(self, buyList):
        modifiedList = buyList.copy()
        for item in modifiedList:
            if item[2] == "2020000000": # Base Price for premium outfits
                item[2] = "2170000000"  # Maximum price for premium outfits
            elif item[2] == "1630000000": # Base Price for Classic outfits
                item[2] = "1750000000"  # Maximum price for Classic outfits
            elif item[2] == "25200": # This is a testing case only
                item[2] = "25200"
            else:
                item[2] = "1180000000" # Maximum price for the rest of the outfits
        return modifiedList
    
    # Login to the marketplace
    async def login(self):
        status = await self.api_handler.is_session_expired()
        if status == 0:
            print("Last session is still valid.")
            self.api_handler.login_status = True
            asyncio.create_task(self.login_status_checker())
        else:   
            if self.api_handler.email and self.api_handler.password:
                status = await self.api_handler.login()
                if status == 1:
                    print("Login successful.")
                    self.api_handler.login_status = True
                    self.api_handler.save_session()
                    asyncio.create_task(self.login_status_checker())
                else:
                    print("Login failed.")
            else:
                print("Please set your credentials first.")
                return
    
    # Initial login status checker
    async def initial_login_check(self):
        status = await self.api_handler.is_session_expired()
        if status == 0:
            print("Session is valid.")
            self.api_handler.login_status = True
            asyncio.create_task(self.login_status_checker())
            print("Login status checker started.")
        else:
            print("Session is invalid or expired.")
            self.api_handler.login_status = False

    # Constantly check the login status every 30 minutes
    async def login_status_checker(self):
        while True:
            await asyncio.sleep(random.uniform(1800, 2400))
            status = await self.api_handler.is_session_expired()
            if status == -1:
                self.api_handler.login_status = False
                print("Session expired. Attempting re-login.....")
                await self.api_handler.login()
                status_after_login_attempt = await self.api_handler.is_session_expired()
                if status_after_login_attempt == 0:
                    self.api_handler.login_status = True
                    print("Re-login successful.")
                else:
                    print("Re-login failed.")
                    break
            else:
                self.api_handler.login_status = True 
                print("Session still valid.")
    
    # Set the delay
    async def set_delay(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("Please select a delay")
        for key, value in self.delay_choices.items():
            print(f"{key}. {value[0]}")

        while True:
            choice = await asyncio.to_thread(input, "Enter your choice: ")
            if choice in self.delay_choices:
                self.delay = choice
                break
            else:
                print(f"{choice} is not a valid choice.")

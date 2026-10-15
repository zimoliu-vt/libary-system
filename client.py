
import requests
import json

# Flask server address
BASE_URL = "http://127.0.0.1:2500"


import time

def add_10000_books():
    total = 10000
    success = 0
    failed = 0

    start = time.perf_counter()

    with requests.Session() as session:
        for i in range(1, total + 1):

            book = {
                "title": f"Test Book {i}",
                "author": f"Author {i}",
                "year": 2000 + (i % 25)
            }

            try:
                response = session.post(
                    BASE_URL + "/books/add",
                    json=book,
                    timeout=30
                )

                if response.status_code == 201:
                    success += 1
                else:
                    failed += 1
                    print(f"Book {i} failed: {response.status_code}")

            except requests.exceptions.RequestException as e:
                failed += 1
                print(f"Book {i} error: {e}")

            if i % 1000 == 0:
                print(f"Progress: {i}/{total}")

    end = time.perf_counter()

    print("\n===== RESULTS =====")
    print("Successful:", success)
    print("Failed:", failed)
    print("Time taken:", round(end - start, 2), "seconds")


def add_book(title, author, year):
    response = requests.post(
        BASE_URL + "/books/add",
        json={
            "title": title,
            "author": author,
            "year": year
        },
        timeout=10
    )
    return response.json()


def remove_book(book_id):
    response = requests.post(
        BASE_URL + "/books/remove",
        json={"id": book_id},
        timeout=10
    )
    return response.json()


def find_book(title):
    response = requests.post(
        BASE_URL + "/books/find",
        json={"title": title},
        timeout=10
    )
    return response.json()


def list_books():
    response = requests.get(
        BASE_URL + "/books",
        timeout=10
    )

    print("HTTP Status:", response.status_code)
    print("Server response:", response.text)

    response.raise_for_status()

    return response.json()


def view_logs():
    response = requests.get(
        BASE_URL + "/logs",
        timeout=10
    )
    return response.json()


def display(data):
    print(json.dumps(data, indent=4))


# Interactive menu
while True:
    print("\n===== LIBRARY SYSTEM =====")
    print("1. Add book")
    print("2. Remove book")
    print("3. Find book")
    print("4. List all books")
    print("5. View activity logs")
    print("6. Add 10,000 test books")
    print("7. Exit")

    choice = input("\nChoose an option: ")

    try:
        if choice == "1":
            title = input("Book title: ")
            author = input("Author: ")
            year = int(input("Publication year: "))

            display(add_book(title, author, year))

        elif choice == "2":
            book_id = int(input("Book ID to remove: "))
            display(remove_book(book_id))

        elif choice == "3":
            title = input("Search title: ")
            display(find_book(title))

        elif choice == "4":
            display(list_books())

        elif choice == "5":
            display(view_logs())

        elif choice == "6":
            confirm = input("Add 10,000 test books? (yes/no): ")

            if confirm.lower() == "yes":
                add_10000_books()

        elif choice == "7":
            print("Goodbye!")
            break

        else:
            print("Invalid option.")

    except ValueError:
        print("Please enter a valid number.")

    except requests.exceptions.RequestException as e:
        print("Server connection error:", e)



def merge_sort(numbers):

    if len(numbers) <= 1:
        return numbers

    middle = len(numbers) // 2

    left = numbers[:middle]
    right = numbers[middle:]

    sorted_numbers_left = merge_sort(left)
    sorted_numbers_right = merge_sort(right)

    merged = []

    i = 0
    j = 0

    while i < len(sorted_numbers_left) and j < len(sorted_numbers_right):
        if sorted_numbers_left[i] > sorted_numbers_right[j]:
            merged.append(sorted_numbers_left[i])
            i += 1
        else:
            merged.append(sorted_numbers_right[j])
            j += 1

    # Append any remaining elements from either list
    merged.extend(sorted_numbers_left[i:])
    merged.extend(sorted_numbers_right[j:])

    return merged


if __name__ == "__main__":
    import random
    import time

    numbers = [random.randint(1, 10) for _ in range(5)]

    start = time.perf_counter()

    result = merge_sort(numbers)

    end = time.perf_counter()

    print("Numbers sorted:", len(result))
    print("Time taken:", round(end - start, 4), "seconds")

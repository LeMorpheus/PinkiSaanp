#include <iostream>
#include <vector>
#include <string>
#include <random>

constexpr int VIEW_SIZE = 11;
constexpr int CENTER = 5;

// Basic moves: Up, Down, Left, Right
const std::vector<std::pair<char, std::pair<int, int>>> MOVES = {
    {'W', {-1, 0}},
    {'A', {0, -1}},
    {'S', {1, 0}},
    {'D', {0, 1}}
};

bool is_safe(char tile) {
    // Avoid walls, hazards, bombs, and other players
    return tile != '#' && tile != '*' && tile != '~' && tile != '!' &&
           tile != '2' && tile != '3' && tile != '4';
}

int main() {
    // Fast I/O
    std::ios_base::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::mt19937 rng(42);
    std::vector<std::string> grid(VIEW_SIZE);

    while (true) {
        for (int i = 0; i < VIEW_SIZE; ++i) {
            if (!(std::cin >> grid[i])) {
                return 0; // Game over / EOF
            }
        }

        std::vector<char> safe_actions;
        for (const auto &[act, delta] : MOVES) {
            int nr = CENTER + delta.first;
            int nc = CENTER + delta.second;
            if (nr >= 0 && nr < VIEW_SIZE && nc >= 0 && nc < VIEW_SIZE) {
                if (is_safe(grid[nr][nc])) {
                    safe_actions.push_back(act);
                }
            }
        }

        char chosen = 'I';
        if (!safe_actions.empty()) {
            std::uniform_int_distribution<size_t> dist(0, safe_actions.size() - 1);
            chosen = safe_actions[dist(rng)];
        }

        // IMPORTANT: Must flush stdout every move!
        std::cout << chosen << "\n" << std::flush;
    }

    return 0;
}

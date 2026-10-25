CXX ?= g++
CXXFLAGS ?= -O3 -std=c++20 -Wall -Wextra

all: bot

bot: bot.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f bot

.PHONY: all clean

var TTQ = require('../index');

var allEvensToFind = 10;
var evensFound = 0;
var evensFailed = 0;

// Test an array of numbers to see if they're all even
var ttq = new TTQ({

  asyncTest: true,

  test: function(numbers, callback) {
    process.nextTick(function() {
      callback(numbers.reduce(function(allEven, number) {
        return number % 2 === 0 && allEven; 
      }, true));
    });
  },

  success: function(numbers) {
    if (++evensFound === allEvensToFind) {
      console.log('Yay! We found', allEvensToFind, 'sets of even numbers');
      process.exit(0);
    } else {
      console.log('Found set of even numbers', evensFound);
    }
  },

  fail: function(numbers) {
    console.log('Failure', ++evensFailed);
  },

  interval: 200
});

setInterval(function() {
  ttq.push(Math.round(Math.random() * 100));
}, 100);
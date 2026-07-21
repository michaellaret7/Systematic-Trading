Order fill functionality

## change the trade ledger to have target fill and actual fill 
--> change the table to be instead of quanityt, it should be filled_quantity and a target quantity 
--> then once the target matches the filled quantity then set the filled at field. 
--> also set the filled price once the order is filled. 

then at the beginning of everyday if there are any orders that are not fully filled then submit the partil fill orders for them.